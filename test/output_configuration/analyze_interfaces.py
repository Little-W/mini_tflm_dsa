#!/usr/bin/env python3
"""在分析图中标记模块端口边界，分别统计输入与输出组合深度。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top", default="npu_output_pipeline")
    parser.add_argument("--tool-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    sys.path.insert(0, str(args.tool_root / "scripts/fpga"))
    import netlist_metrics

    raw = args.netlist.read_bytes()
    if args.netlist.suffix == ".gz":
        raw = gzip.decompress(raw)
    module = json.loads(raw)["modules"][args.top]
    origins = netlist_metrics.register_origins(args.pre_lut, top=args.top)
    for name, origin in origins.items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    next_bit = max(bit for net in module["netnames"].values()
                   for bit in net["bits"] if isinstance(bit, int)) + 1
    for name, port in module["ports"].items():
        if name in ("clk", "rst_n"):
            continue
        for index, bit in enumerate(port["bits"]):
            if not isinstance(bit, int):
                continue
            for direction in ("input", "output"):
                if port["direction"] not in (direction, "inout"):
                    continue
                cell_name = f"boundary_{direction}_{name}_{index}"
                data, result = ("0", bit) if direction == "input" else (bit, next_bit)
                next_bit += direction == "output"
                module["cells"][cell_name] = {
                    "type": "FDRE", "parameters": {},
                    "attributes": {"fpga_register_origin": f"{direction}:{name}[{index}]"},
                    "port_directions": {"C": "input", "CE": "input", "R": "input",
                                        "D": "input", "Q": "output"},
                    "connections": {"C": ["0"], "CE": ["1"], "R": ["0"],
                                    "D": [data], "Q": [result]}}
    is_input = lambda name, cell, port: name.startswith("boundary_input_")
    is_output = lambda name, cell, port: name.startswith("boundary_output_")
    is_internal = lambda name, cell, port: not name.startswith("boundary_")
    report = {
        "mapped_sha256": hashlib.sha256(raw).hexdigest(),
        "boundary_registers_are_analysis_only": True}
    for name, start, end in (
            ("input_to_register", is_input, is_internal),
            ("register_to_output", is_internal, is_output),
            ("input_to_output", is_input, is_output)):
        report[name] = netlist_metrics.connected_paths(
            module, limit=40, group_limit=24, root_filter=start, sink_filter=end)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: value["longest_register_path_cells"] for name, value in report.items()
                      if isinstance(value, dict)}))


if __name__ == "__main__":
    main()
