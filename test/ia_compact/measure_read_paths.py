#!/usr/bin/env python3
"""统计 IA 存储读数据及偏移到阵列输出的连接路径和组合 DSP。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import analyze, connected_paths, register_origins

INPUTS = ("ram_port_rd_data", "compact_offset", "compact_mode")
INPUT_PREFIX = "observed_read_input_"
OUTPUT_PREFIX = "observed_read_output_"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapped", type=Path, required=True)
    parser.add_argument("--pre-lut", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())["modules"]["ia_loader_cache_mgr"]
    for name, origin in register_origins(args.pre_lut).items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    result = {
        "mapped_sha256": hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
        "pre_lut_sha256": hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
        "complete_module": analyze(module),
        "input_paths": {},
        "dsp_cells": [{"cell": name, "source": cell.get("attributes", {}).get("src", ""),
                       "parameters": cell["parameters"]}
                      for name, cell in module["cells"].items() if cell["type"] == "DSP48E1"],
    }
    next_bit = max(bit for cell in module["cells"].values()
                   for bits in cell["connections"].values() for bit in bits if isinstance(bit, int)) + 1
    # 观察源与观察终点仅用于组合连接分析，不改变综合网表和原始资源统计。
    for input_name in INPUTS:
        for index, bit in enumerate(module["ports"][input_name]["bits"]):
            if not isinstance(bit, int):
                continue
            name = f"{INPUT_PREFIX}{input_name}[{index}]"
            module["cells"][name] = {
                "type": "FDRE", "parameters": {},
                "attributes": {"fpga_register_origin": f"input {input_name} [{index}]"},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [next_bit], "Q": [bit]},
            }
            next_bit += 1
    for index, bit in enumerate(module["ports"]["ia_out"]["bits"]):
        name = f"{OUTPUT_PREFIX}ia_out[{index}]"
        module["cells"][name] = {
            "type": "FDRE", "parameters": {},
            "attributes": {"fpga_register_origin": f"output ia_out [{index}]"},
            "port_directions": {"D": "input", "Q": "output"},
            "connections": {"D": [bit], "Q": [next_bit]},
        }
        next_bit += 1
    for input_name in INPUTS:
        prefix = INPUT_PREFIX + input_name + "["
        paths = connected_paths(module, limit=100000, group_limit=100000,
                                root_filter=lambda name, cell, port: name.startswith(prefix),
                                sink_filter=lambda name, cell, port: name.startswith(OUTPUT_PREFIX))
        if not paths["graph_complete"]:
            raise RuntimeError("Mapped IA cache connectivity graph is incomplete")
        selected = paths["register_to_register_paths"]
        result["input_paths"][input_name] = {
            "connected": bool(selected),
            "longest_path_cells": paths["longest_register_path_cells"],
            "longest_paths": selected[:1],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "logic_lut_cells": result["complete_module"]["resources"]["logic_lut_cells"],
        "dsp_cells": len(result["dsp_cells"]),
        "input_path_cells": {name: path["longest_path_cells"]
                             for name, path in result["input_paths"].items()},
    }))


if __name__ == "__main__":
    main()
