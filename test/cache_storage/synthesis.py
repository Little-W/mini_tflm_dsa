#!/usr/bin/env python3
"""对相同缓存参数执行独立 FPGA 综合并记录资源和组合逻辑级数。"""
import argparse
import collections
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import resource
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))

from netlist_metrics import analyze, connected_paths, register_origins


def response_paths(design):
    """只增加观察终点，统计寄存器到公开响应端口的组合路径。"""
    observed = copy.deepcopy(design)
    for cell in observed["cells"].values():
        if re.fullmatch(r"FD(?:RE|SE|CE|PE)(?:_1)?", cell["type"]):
            cell["connections"] = {name: bits for name, bits in cell["connections"].items()
                                   if name in ("Q", "C")}
    synthetic_bit = max(bit for cell in design["cells"].values()
                        for bits in cell["connections"].values() for bit in bits
                        if isinstance(bit, int)) + 1
    for port in ("rsp_data", "rsp_valid", "rsp_error", "req_ready"):
        for index, bit in enumerate(observed["ports"][port]["bits"]):
            observed["cells"][f"output_capture_{port}[{index}]"] = {
                "type": "FDRE", "attributes": {}, "parameters": {},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [bit], "Q": [synthetic_bit]}}
            synthetic_bit += 1
    paths = connected_paths(observed, limit=10000, group_limit=10000)
    result = {}
    for path in paths["register_to_register_paths"]:
        endpoint = path["endpoint"]["cell"]
        if endpoint.startswith("output_capture_"):
            port = endpoint.removeprefix("output_capture_").split("[")[0]
            result.setdefault(port, path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--fpga", action="store_true", help="综合FPGA专用组合原语")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/dma/cache/conv_read_cache.sv",
               ROOT / "rtl/npu/dma/cache/conv_sdp_ram.sv",
               ROOT / "rtl/npu/conv/conv_axi_span_reader.sv",
               ROOT / "rtl/common/REGFILE.v"]
    if args.reference:
        sources = [args.reference.resolve() / path.name for path in sources[:3]]
        storage = args.reference.resolve() / 'REGFILE.v'
        if storage.is_file():
            sources.append(storage)
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    snapshot = out / "sources"
    snapshot.mkdir(exist_ok=True)
    archived_sources = []
    for source in sources:
        archived = snapshot / source.name
        shutil.copyfile(source, archived)
        archived_sources.append(archived)
    script = out / "run.ys"
    mapped = out / "mapped.json"
    pre_lut = out / "pre_lut.il"
    if args.fpga:
        import pyosys
        library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
        model = out / "lut6_2.sv"
        model.write_text(re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S).group(0) + "\n")
    primitive_args = ("-D XILINX_FPGA=1 --blackboxed-module LUT6_2 -v " +
                      shlex.quote(str(model)) + " ") if args.fpga else ""
    script.write_text("read_slang " + primitive_args +
        "--top conv_windowed_cache -GSETS=128 -GWAYS=2 -GBUS_WIDTH=64 " +
        " ".join(shlex.quote(str(path)) for path in archived_sources) + "\n" +
        ("read_verilog -lib -specify -overwrite +/xilinx/cells_sim.v\n" if args.fpga else "") +
        "hierarchy -check -top conv_windowed_cache\n" +
        "synth_xilinx -top conv_windowed_cache -family xc7 -noiopad -noclkbuf -flatten -run begin:map_luts\n" +
        "write_rtlil " + shlex.quote(str(pre_lut)) + "\n" +
        "synth_xilinx -top conv_windowed_cache -family xc7 -noiopad -noclkbuf -flatten -run map_luts:\n" +
        "check -assert\nstat -tech xilinx\nwrite_json " + shlex.quote(str(mapped)) + "\n")
    with (out / "synthesis.log").open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                        "--worker", str(script)], stdout=log, stderr=subprocess.STDOUT, check=True)
    module_spec = importlib.util.spec_from_file_location("fpga_synth", ROOT / "scripts/fpga/open_fpga_synth.py")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    design = json.loads(mapped.read_text())["modules"]["conv_windowed_cache"]
    cells = design["cells"]
    for name, origin in register_origins(pre_lut).items():
        if name in cells:
            cells[name].setdefault("attributes", {})["fpga_register_origin"] = origin
    metrics = analyze(design)
    counts = collections.Counter(cell["type"] for cell in cells.values())
    path = module.logic_depth(cells)
    result = {"source_sha256": hashes, "source_snapshot": str(snapshot),
              "configuration": {"SETS": 128, "WAYS": 2, "BUS_WIDTH": 64, "LINE_BYTES": 16},
              "maximum_resident_kib": resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
              "fpga": args.fpga,
              "lut_cells": sum(value for cell, value in counts.items() if re.fullmatch("LUT[1-6](?:_2)?", cell)),
              "flip_flops": sum(value for cell, value in counts.items() if cell.startswith(("FDCE", "FDPE", "FDRE", "FDSE"))),
              "longest_combinational_path_cells": len(path),
              "longest_combinational_path": path, "cell_counts": dict(sorted(counts.items())),
              "connected_path_metrics": metrics["paths"], "resources": metrics["resources"],
              "response_output_paths": response_paths(design)}
    assert hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("lut_cells", "flip_flops", "longest_combinational_path_cells")}))


if __name__ == "__main__":
    main()
