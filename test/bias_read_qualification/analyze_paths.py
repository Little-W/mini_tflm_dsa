#!/usr/bin/env python3
"""分析完整偏置网表的接口深度及 RAM 实际读取使能路径。"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--netlist", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "scripts/fpga"))
    import netlist_metrics

    raw = args.netlist.read_bytes()
    if args.netlist.suffix == ".gz":
        raw = gzip.decompress(raw)
    module = json.loads(raw)["modules"]["bias_loader"]
    origins = netlist_metrics.register_origins(args.pre_lut, top="bias_loader")
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
    inputs = lambda name, cell, port: name.startswith("boundary_input_")
    outputs = lambda name, cell, port: name.startswith("boundary_output_")
    internal = lambda name, cell, port: not name.startswith("boundary_")
    report = dict(mapped_sha256=hashlib.sha256(raw).hexdigest(),
                  boundary_registers_are_analysis_only=True)
    for name, start, end in (
            ("input_to_register", inputs, internal),
            ("register_to_output", internal, outputs),
            ("input_to_output", inputs, outputs)):
        report[name] = netlist_metrics.connected_paths(
            module, limit=12, group_limit=12, root_filter=start, sink_filter=end)
    is_ram_enable = lambda name, cell, port: (
        cell["type"].startswith("RAMB") and port in ("ENARDEN", "ENBWREN"))
    report["read_enable_paths"] = {}
    for signal in ("group_read_start", "group_read_idx", "is_mode", "all_registers"):
        selected = lambda name, cell, port: (
            name.startswith(f"boundary_input_{signal}_")
            if signal != "all_registers" else internal(name, cell, port))
        report["read_enable_paths"][signal] = netlist_metrics.connected_paths(
            module, limit=8, group_limit=8, root_filter=selected, sink_filter=is_ram_enable)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: value["longest_register_path_cells"]
                      for name, value in report.items()
                      if isinstance(value, dict) and "longest_register_path_cells" in value}))
    print(json.dumps({name: value["longest_register_path_cells"]
                      for name, value in report["read_enable_paths"].items()}))


if __name__ == "__main__":
    main()
