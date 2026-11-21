#!/usr/bin/env python3
"""Check shared SRAM dimensions, synchronous ports, and frame-store memories."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def value(parameters, name):
    result = parameters[name]
    return int(result, 2) if isinstance(result, str) else int(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--yosys", default="yosys")
    parser.add_argument("--bank-bytes", type=int, nargs="+", choices=(2048,4096,8192), default=[2048,4096,8192])
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__).resolve(), root / "rtl/npu/buffers/ia_ps_shared_ram.sv",
               root / "rtl/npu/ps_compact/ps_frame_store.sv", root / "rtl/npu/ps_compact/ps_adaptive_codec.sv",
               root / "rtl/npu/loaders/ia_loader_cache_mgr.sv", root / "rtl/common/pseudo_dual_port_ram.v",
               root / "rtl/common/regfile.v", root / "rtl/common/parallel_prefix_add.sv"]
    before = {str(path.relative_to(root)): digest(path) for path in sources}
    import pyosys
    sys.path.insert(0, str(root / "scripts/fpga"))
    from open_fpga_synth import primitive_models
    primitive_options, primitive_manifest = primitive_models(
        out, [str(path) for path in sources if path.suffix in (".v", ".sv")],
        Path(pyosys.__file__).parent / "share/xilinx")
    profiles = []
    for bank_bytes in args.bank_bytes:
        for banks in (6, 7, 8, 9):
            for kind in (("shared", "store", "ia") if banks == 7 else ("shared", "store")):
                name = f"{kind}_{bank_bytes}_bytes_{banks}_banks"
                json_path = out / f"{name}.json"
                if kind == "shared":
                    read = ("read_slang --top ia_ps_shared_ram -D SYNTHESIS "
                            f"-GBANK_BYTES={bank_bytes} -GTOTAL_BYTES={banks * bank_bytes} rtl/npu/buffers/ia_ps_shared_ram.sv")
                elif kind == "store":
                    read = ("read_slang --top ps_frame_store -D SYNTHESIS -GEXTERNAL_RAM=1 "
                            f"-GPOOL_BYTES={(banks-1)*bank_bytes} -GBANK_BYTES={bank_bytes} "
                            f"-GMAX_FRAME_ROWS={bank_bytes//8} -GDIRECTORY_ROWS=1024 "
                            f"-GRAM_ADDR_BITS={(banks*(bank_bytes//16)-1).bit_length()} "
                            "rtl/npu/ps_compact/ps_frame_store.sv rtl/npu/ps_compact/ps_adaptive_codec.sv")
                else:
                    read = ("read_slang --top ia_loader_cache_mgr -D SYNTHESIS -GEXTERNAL_RAM=1 "
                            f"-GDATA_WIDTH=16 -GSIZE=16 -GCACHE_BLOCKS={bank_bytes//128} "
                            f"-GRAM_WORD_ADDR_WIDTH={(banks*(bank_bytes//16)-1).bit_length()} "
                            "rtl/npu/loaders/ia_loader_cache_mgr.sv rtl/common/pseudo_dual_port_ram.v")
                script = out / f"{name}.ys"
                read += " rtl/common/regfile.v rtl/common/parallel_prefix_add.sv"
                read = read.replace("read_slang ", "read_slang " + primitive_options + " ", 1)
                memory_passes = "\nopt\nmemory_dff\n" + ("" if kind == "ia" else "memory_share\nopt_clean\n")
                script.write_text(read + memory_passes + "memory_collect\nopt_clean\n"
                                  f"check -assert\nstat\nwrite_json {json_path}\n")
                command = [args.yosys, "-Q", "-T", "-s", str(script)]
                with (out / f"{name}.log").open("w") as log:
                    result = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError(f"Structural synthesis failed: {name}")
                design = json.loads(json_path.read_text())
                cells = [(module_name + "." + cell_name, cell)
                         for module_name, module in design["modules"].items()
                         for cell_name, cell in module.get("cells", {}).items()]
                latches = [cell_name for cell_name, cell in cells if "latch" in cell["type"].lower()]
                if latches:
                    raise RuntimeError(f"Latches found: {latches}")
                memories = []
                for cell_name, cell in cells:
                    if cell["type"] != "$mem_v2":
                        continue
                    p = cell["parameters"]
                    memories.append(dict(name=cell_name, **{key.lower(): value(p, key) for key in
                        ("WIDTH", "SIZE", "RD_PORTS", "WR_PORTS", "RD_CLK_ENABLE", "WR_CLK_ENABLE")}))
                if kind == "shared":
                    if len(memories) != banks or any(
                        (m["width"], m["size"], m["rd_ports"], m["wr_ports"],
                         m["rd_clk_enable"], m["wr_clk_enable"]) != (128, bank_bytes//16, 1, 1, 1, 1)
                        for m in memories):
                        raise RuntimeError(f"Shared memory geometry or synchronous ports differ: {name}")
                elif kind == "store":
                    decoded = [m for m in memories if m["name"].endswith(".u_decoded.mem")]
                    if len(decoded) != 1 or any(decoded[0][key] != expected for key, expected in
                        dict(width=512, size=8, rd_ports=1, wr_ports=1, rd_clk_enable=1, wr_clk_enable=1).items()):
                        raise RuntimeError(f"Decoded FIFO dimensions or timing differ: {name}")
                    if len(memories) != 1:
                        raise RuntimeError(f"External frame storage contains an unexpected memory: {name}")
                else:
                    expected_control = {"l1_last_pipe": (1, 16), "ram_rd_en_d1": (1, 16),
                                        "rd_addr_pipe": ((bank_bytes//4-1).bit_length(), 16), "rd_en_pipe": (1, 16),
                                        "tile_last_pipe": (1, 16), "slot_written_cols": (5, bank_bytes//64)}
                    found_control = set()
                    for memory in memories:
                        control_name = memory["name"].removeprefix("ia_loader_cache_mgr.")
                        if control_name not in expected_control or (memory["width"], memory["size"]) != expected_control[control_name]:
                            raise RuntimeError(f"External IA contains an unexpected memory: {memory}")
                        found_control.add(control_name)
                    if found_control != set(expected_control):
                        raise RuntimeError("External IA control registers differ")
                profiles.append(dict(name=name, total_data_bytes=banks*bank_bytes, bank_bytes=bank_bytes, passed=True,
                                     memories=memories, latches=0, command=command,
                                     cell_count=len(cells), script_sha256=digest(script),
                                     netlist_sha256=digest(json_path)))
    proof_cases = 0
    for banks in range(2, 9):
        for cap in range(2, min(banks, 4)+1):
            lead = (banks+cap-1)//cap
            for length in range(1, max(args.bank_bytes)//8+1):
                budget = (cap*length+banks-1)//banks
                for committed in range(1, length+1):
                    released = min(length, committed+lead)
                    remaining_old = (cap*(length-released)+banks-1)//banks
                    new_prefix = (cap*committed+banks-1)//banks
                    if remaining_old+new_prefix > budget:
                        raise RuntimeError("Read-prefix bank bound failed")
                    proof_cases += 1
    if before != {str(path.relative_to(root)): digest(path) for path in sources}:
        raise RuntimeError("Sources changed during structural checks")
    result = dict(passed=True, source_sha256=before, profiles=profiles, primitive_models=primitive_manifest,
                  checked_read_prefix_cases=proof_cases,
                  yosys_version=subprocess.check_output([args.yosys, "-V"], text=True).strip())
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(passed=True, profiles=len(profiles), checked_read_prefix_cases=proof_cases)))


if __name__ == "__main__":
    main()
