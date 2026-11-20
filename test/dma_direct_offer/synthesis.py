#!/usr/bin/env python3
"""综合 DMA 描述符控制和窗口队列，测量前端接口之间的组合连接。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins, resources

TOP = "axi_dual_block_dma"
CHILDREN = ("axi_linear_block_dma", "conv_im2col_frontend", "conv_axi_read_guard",
            "axi_write_page_guard", "conv_axi_read_mux")
NAMES = ("rtl/npu/conv/conv_im2col_pkg.sv", "rtl/npu/dma/axi_dual_block_dma.sv",
         "rtl/npu/dma/conv_window_queue.sv", "rtl/npu/dma/axi_linear_block_dma.sv",
         "rtl/npu/conv/conv_im2col_frontend.sv", "rtl/npu/conv/conv_axi_read_guard.sv",
         "rtl/npu/dma/axi_write_page_guard.sv", "rtl/npu/conv/conv_axi_read_mux.sv")


def observe_paths(original, pre_lut):
    module = copy.deepcopy(original)
    for name, origin in register_origins(pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    next_bit = max(bit for cell in module["cells"].values() for bits in cell["connections"].values()
                   for bit in bits if isinstance(bit, int)) + 1
    groups = {}
    boundaries = []

    def observe(label, bits, source):
        nonlocal next_bit
        names = []
        for index, bit in enumerate(bits):
            if not isinstance(bit, int):
                continue
            name = f"interface_observation_{label}[{index}]"
            names.append(name)
            module["cells"][name] = dict(type="FDRE", parameters={},
                attributes={"fpga_register_origin": f"interface {label} [{index}]"},
                port_directions={"D": "input", "Q": "output"},
                connections={"D": [next_bit] if source else [bit],
                             "Q": [bit] if source else [next_bit]})
            next_bit += 1
        groups[label] = names

    for name, cell in list(module["cells"].items()):
        if cell["type"] == "$scopeinfo":
            assert not cell["connections"]
            del module["cells"][name]
        elif cell["type"].startswith(CHILDREN):
            boundaries.append(dict(cell=name, type=cell["type"]))
            del module["cells"][name]
            for port, bits in cell["connections"].items():
                if port not in ("clk", "rst_n"):
                    observe(name + "." + port, bits, cell["port_directions"][port] == "output")
    for name, port in module["ports"].items():
        if name not in ("clk", "rst_n"):
            observe(name, port["bits"], port["direction"] == "input")
    frontend = next(item["cell"] for item in boundaries if item["type"].startswith("conv_im2col_frontend"))
    linear = next(item["cell"] for item in boundaries if item["type"].startswith("axi_linear_block_dma"))
    report = {"boundaries": boundaries, "paths": {}}
    sinks = ("tile_p0", "tile_q0", "tile_rows", "tile_cols", "tile_slot", "tile_group", "tile_valid")
    for source in (frontend + ".tile_ready", frontend + ".wr_last", linear + ".rd_finish_beat"):
        roots = set(groups[source])
        targets = set(name for sink in sinks for name in groups[frontend + "." + sink])
        paths = connected_paths(module, limit=100000, group_limit=100000,
            root_filter=lambda name, cell, port: name in roots,
            sink_filter=lambda name, cell, port: name in targets)
        if not paths["graph_complete"]:
            raise RuntimeError("Incomplete interface path graph")
        report["paths"][source] = {}
        for sink in sinks:
            names = set(groups[frontend + "." + sink])
            selected = [path for path in paths["register_to_register_paths"] if path["endpoint"]["cell"] in names]
            report["paths"][source][sink] = dict(connected=bool(selected),
                longest_path_cells=max((path["combinational_cells"] for path in selected), default=0),
                longest_paths=selected[:1])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference-ref")
    args = parser.parse_args()
    out = args.out.resolve()
    snapshots = out / "sources"
    snapshots.mkdir(parents=True, exist_ok=True)
    sources, hashes = [], {}
    for name in NAMES:
        data = (read_rtl_source(f"{args.reference_ref}:{name}", cwd=ROOT)
                if args.reference_ref else (ROOT / name).read_bytes())
        hashes[name] = hashlib.sha256(data).hexdigest()
        path = snapshots / Path(name).name
        path.write_bytes(data)
        if path.stem in CHILDREN:
            text = data.decode()
            header_end = re.search(r"^\s*\);", text, re.M).end()
            path = snapshots / (path.stem + "_interface.sv")
            path.write_text(text[:header_end] + "\nendmodule\n")
        sources.append(path)
    mapped, pre_lut = out / "mapped.json", out / "pre_lut.il"
    script = out / "run.ys"
    script.write_text(f"read_slang --keep-hierarchy --top {TOP} -GSIZE=64 -GIM2COL_SIZE=16 "
        "-GBUS_WIDTH=64 -GCACHE_BLOCKS=64 -GCONV_CACHE_SETS=128 " +
        " ".join(shlex.quote(str(path)) for path in sources) + "\n" +
        "blackbox " + " ".join(name + "*" for name in CHILDREN) + "\n" +
        f"hierarchy -check -top {TOP}\n" +
        f"synth_xilinx -top {TOP} -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
        "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
        f"synth_xilinx -top {TOP} -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
        "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
    with (out / "synthesis.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    module = json.loads(mapped.read_text())["modules"][TOP]
    report = dict(scope="axi_dual_block_dma and complete conv_window_queue; five child interfaces are black boxes",
        family="xc7", reference_ref=args.reference_ref, source_sha256=hashes,
        configuration=dict(SIZE=64, IM2COL_SIZE=16, BUS_WIDTH=64, CACHE_BLOCKS=64, CONV_CACHE_SETS=128),
        resources=resources(module["cells"]), interface_paths=observe_paths(module, pre_lut),
        maximum_resident_kib=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
        mapped_sha256=hashlib.sha256(mapped.read_bytes()).hexdigest())
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(dict(resources=report["resources"], maximum_resident_kib=report["maximum_resident_kib"],
        paths={source: {sink: data["longest_path_cells"] for sink, data in sinks.items()}
               for source, sinks in report["interface_paths"]["paths"].items()})))


if __name__ == "__main__":
    main()
