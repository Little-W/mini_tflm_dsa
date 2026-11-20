#!/usr/bin/env python3
"""统计 IA 坐标寄存器到 DMA 请求、请求资格和公开坐标端口的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import analyze, connected_paths, register_origins

OUTPUTS = ("ext_dma_start", "load_ia_req", "ext_dma_p0", "ext_dma_q0")
REGISTERS = ("p0_base_q", "q0_base_q", "demand_p0_q", "demand_q0_q")
CAPTURE_PREFIX = "observed_output_"


def report_ports(module, root_filter=None):
    paths = connected_paths(module, limit=100000, group_limit=100000,
                            root_filter=root_filter,
                            sink_filter=lambda name, cell, port: name.startswith(CAPTURE_PREFIX))
    result = {}
    for output in OUTPUTS:
        prefix = CAPTURE_PREFIX + output + "["
        matches = [path for path in paths["register_to_register_paths"]
                   if path["endpoint"]["cell"].startswith(prefix)]
        result[output] = {
            "connected": bool(matches),
            "longest_path_cells": max((path["combinational_cells"] for path in matches), default=0),
            "longest_paths": matches[:1],
        }
    if not paths["graph_complete"]:
        raise RuntimeError("Mapped IA connectivity graph is incomplete")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())["modules"]["ia_loader"]
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    result = {
        "mapped_sha256": hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
        "pre_lut_sha256": hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
        "complete_module": analyze(module),
        "register_groups": {},
    }
    # 观察终点只用于分析连接关系，不加入综合网表或资源统计。
    next_bit = max(bit for cell in module["cells"].values()
                   for bits in cell["connections"].values() for bit in bits
                   if isinstance(bit, int)) + 1
    for output in OUTPUTS:
        for index, bit in enumerate(module["ports"][output]["bits"]):
            name = f"{CAPTURE_PREFIX}{output}[{index}]"
            if name in module["cells"]:
                raise ValueError("Analysis endpoint name already exists: " + name)
            module["cells"][name] = {
                "type": "FDRE", "attributes": {}, "parameters": {},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [bit], "Q": [next_bit]},
            }
            next_bit += 1
    result["output_paths"] = report_ports(module)
    for register in REGISTERS:
        def selected(name, cell, port):
            origin = cell.get("attributes", {}).get("fpga_register_origin") or ""
            return bool(re.match(re.escape(register) + r"(?: \[|$)", origin))

        result["register_groups"][register] = report_ports(module, selected)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "module_max": result["complete_module"]["paths"]["longest_register_path_cells"],
        "outputs": {name: data["longest_path_cells"] for name, data in result["output_paths"].items()},
        "register_groups": {
            name: {port: data["longest_path_cells"] if data["connected"] else None
                   for port, data in group.items()}
            for name, group in result["register_groups"].items()
        },
    }))


if __name__ == "__main__":
    main()
