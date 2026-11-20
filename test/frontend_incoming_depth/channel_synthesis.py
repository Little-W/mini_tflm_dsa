#!/usr/bin/env python3
"""测量实际 DMA 配置接受条件到通道位置次值的组合路径。"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
import open_fpga_synth as flow
from remap_fpga_luts import physical_cost_library, mapping_commands
from netlist_metrics import connected_paths, register_origins, resources


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(script, log):
    with log.open("w") as stream:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
            cwd=script.parent, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lock-file", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof_dir = args.proof.resolve()
    proof = json.loads((proof_dir / "summary.json").read_text())
    frontend = ROOT / "rtl/npu/conv/conv_im2col_frontend.sv"
    if not proof["passed"] or proof["source_sha256"] != digest(frontend):
        raise RuntimeError("The measured source differs from the channel proof")
    dma_path = ROOT / "rtl/npu/dma/axi_dual_block_dma.sv"
    dma = dma_path.read_text()
    if dma != read_rtl_source(proof["reference_commit"] + ":rtl/npu/dma/axi_dual_block_dma.sv", cwd=ROOT, text=True):
        raise RuntimeError("The configuration connection differs from the fixed source")
    ready = re.search(r"    assign conv_cfg_ready\s*=.*?;", dma, re.S)[0]
    fire = re.search(r"    assign cfg_fire\s*=.*?;", dma, re.S)[0]
    if ".cfg_valid(cfg_fire && conv_enable)" not in dma:
        raise RuntimeError("Unexpected frontend configuration connection")
    tool = runpy.run_path(str(ROOT / "test/frontend_incoming_depth/channel_formal.py"))
    reference = read_rtl_source(proof["reference_commit"] + ":rtl/npu/conv/conv_im2col_frontend.sv", cwd=ROOT, text=True)
    cases = {}
    with args.lock_file.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for label, text in (("reference", reference), ("current", frontend.read_text())):
            folder = out / label
            folder.mkdir(exist_ok=True)
            unit = tool["unit"](text, "channel_write", label == "current", True)
            unit = unit.replace("input logic [1-1:0] i_cfg_valid,\n", "")
            unit = unit.replace("cfg_valid <= i_cfg_valid;\n", "")
            unit = unit.replace("output logic [18:0] observed", "input logic i_conv_cfg_valid,i_rd_busy,i_rd_done,i_conv_enable,\noutput logic [18:0] observed")
            connections = """
logic conv_cfg_valid,rd_busy,rd_done,conv_enable,conv_cfg_ready,fe_cfg_ready,cfg_fire;
always_ff @(posedge clk) begin
  conv_cfg_valid<=i_conv_cfg_valid;
  rd_busy<=i_rd_busy;
  rd_done<=i_rd_done;
  conv_enable<=i_conv_enable;
end
assign fe_cfg_ready=cfg_ready;
assign cfg_valid=cfg_fire && conv_enable;
""" + ready + "\n" + fire + "\n"
            unit = unit.replace("endmodule\n", connections + "endmodule\n")
            source = folder / "registered.sv"
            source.write_text(unit)
            import pyosys
            options, primitives = flow.primitive_models(folder, [str(source)], Path(pyosys.__file__).parent / "share/xilinx")
            pre_lut, script = folder / "pre_lut.il", folder / "pre_lut.ys"
            script.write_text("read_slang --keep-hierarchy --top channel_write -D XILINX_FPGA " + options + " " + shlex.quote(str(source)) +
                "\nread_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\nhierarchy -check -top channel_write\n"
                "synth_xilinx -top channel_write -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n"
                "write_rtlil " + shlex.quote(str(pre_lut)) + "\n")
            run(script, folder / "pre_lut.log")
            raw, library = folder / "native.lut", folder / "physical.lut"
            prepare = folder / "library.ys"
            prepare.write_text("read_verilog -lib -specify +/xilinx/cells_sim.v\nadd -mod library_top\n"
                "abc9_ops -prep_lut 0\nabc9_ops -write_lut " + shlex.quote(str(raw)) + "\n")
            run(prepare, folder / "library.log")
            library_info = physical_cost_library(raw, library, 8)
            script = folder / "mapping.ys"
            script.write_text(mapping_commands("channel_write", pre_lut, folder, "physical-cost", 6667, 300, library))
            log = folder / "mapping.log"
            run(script, log)
            if "Networks are equivalent." not in log.read_text():
                raise RuntimeError("ABC9 did not verify mapping")
            mapped = folder / "mapped.json"
            module = json.loads(mapped.read_text())["modules"]["channel_write"]
            for name, origin in register_origins(pre_lut).items():
                if name in module["cells"]:
                    module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
            module["cells"] = {name: cell for name, cell in module["cells"].items() if cell["type"] != "$scopeinfo"}

            def target(name, cell, port):
                return port == "D" and re.search(r"^observed \[(?:[0-9]|1[0-5])\]$", cell.get("attributes", {}).get("fpga_register_origin", "")) is not None

            paths = {"all_to_channel": connected_paths(module, limit=5, group_limit=5, sink_filter=target)}
            for selector in ("cache_cfg_ready", "conv_cfg_valid", "state", "wr_ready", "tile_valid"):
                paths[selector + "_to_channel"] = connected_paths(module, limit=3, group_limit=3,
                    root_filter=lambda n,c,p: selector == c.get("attributes", {}).get("fpga_register_origin", "").split(" [")[0],
                    sink_filter=target)
            if not all(value["graph_complete"] for value in paths.values()):
                raise RuntimeError("Incomplete dependency graph")
            row = dict(resources=resources(module["cells"]), paths=paths,
                source_sha256=digest(source), mapped_sha256=digest(mapped), pre_lut_sha256=digest(pre_lut),
                log_sha256=digest(log), primitive_models=primitives, library=library_info, abc9_equivalent=True)
            cases[label] = row
            (folder / "summary.json").write_text(json.dumps(row, indent=2) + "\n")
            print(label, row["resources"]["logic_lut_cells"],
                {name: value["longest_register_path_cells"] for name, value in paths.items()}, flush=True)
    report = dict(passed=True, reference_commit=proof["reference_commit"], source_sha256=proof["source_sha256"],
        reference_sha256=proof["reference_sha256"], dma_sha256=digest(dma_path),
        actual_dma_cfg_fire_connection=True, actual_frontend_ready_and_channel_process=True,
        SIZE=16, LANES=4, BUS_WIDTH=64, proof_summary_sha256=digest(proof_dir / "summary.json"),
        mapping=dict(mode="physical-cost", max_lut_inputs=8, delay_target_ps=6667, wire_delay_ps=300),
        boundary="registered frontend context and cache ready through actual DMA cfg_fire to channel next value",
        metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
