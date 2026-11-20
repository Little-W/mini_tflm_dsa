#!/usr/bin/env python3
"""统计 IA 配置输入、已保存配置和分块步长之间的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import analyze, connected_paths, register_origins

REGISTERS = ("global_reduction_q", "cfg_n", "packed_k_tiles_q", "tile_packed_q", "cfg_use_16bits")
TARGETS = ("packed_k_tiles_q", "u_ctrl.tile_row_step_b", "u_ctrl.l2_group_row_step_b")
INPUTS = ("cfg_global_reduction", "n", "init_cfg")
INPUT_PREFIX = "observed_config_input_"


def signal_name(cell):
    return (cell.get("attributes", {}).get("fpga_register_origin") or "").split(" [")[0]


def target_paths(module, root_filter=None):
    paths = connected_paths(module, limit=100000, group_limit=100000, root_filter=root_filter,
                            sink_filter=lambda name, cell, port: signal_name(cell) in TARGETS)
    if not paths["graph_complete"]:
        raise RuntimeError("Mapped IA connectivity graph is incomplete")
    result = {}
    for target in TARGETS:
        selected = [path for path in paths["register_to_register_paths"]
                    if (path["endpoint"].get("register_origin") or "").split(" [")[0] == target]
        result[target] = {
            "connected": bool(selected),
            "longest_path_cells": max((path["combinational_cells"] for path in selected), default=0),
            "longest_paths": selected[:1],
        }
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
        "all_registers": target_paths(module),
        "register_groups": {},
        "input_ports": {},
    }
    for register in REGISTERS:
        result["register_groups"][register] = target_paths(
            module, lambda name, cell, port: signal_name(cell) == register)

    # 输入端观察源仅参与连接分析，不进入综合网表、资源统计或寄存器间结果。
    next_bit = max(bit for cell in module["cells"].values()
                   for bits in cell["connections"].values() for bit in bits if isinstance(bit, int)) + 1
    for input_name in INPUTS:
        for index, bit in enumerate(module["ports"][input_name]["bits"]):
            if not isinstance(bit, int):
                continue
            name = f"{INPUT_PREFIX}{input_name}[{index}]"
            if name in module["cells"]:
                raise ValueError("Analysis input name already exists: " + name)
            module["cells"][name] = {
                "type": "FDRE", "parameters": {},
                "attributes": {"fpga_register_origin": f"input {input_name} [{index}]"},
                "port_directions": {"D": "input", "Q": "output"},
                "connections": {"D": [next_bit], "Q": [bit]},
            }
            next_bit += 1
    for input_name in INPUTS:
        prefix = INPUT_PREFIX + input_name + "["
        result["input_ports"][input_name] = target_paths(
            module, lambda name, cell, port: name.startswith(prefix))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({
        "module_register_max": result["complete_module"]["paths"]["longest_register_path_cells"],
        "register_targets": {target: item["longest_path_cells"] if item["connected"] else None
                             for target, item in result["all_registers"].items()},
        "input_ports": {name: {target: item["longest_path_cells"] if item["connected"] else None
                               for target, item in targets.items()}
                        for name, targets in result["input_ports"].items()},
    }))


if __name__ == "__main__":
    main()
