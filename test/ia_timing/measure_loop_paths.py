#!/usr/bin/env python3
"""统计 IA 组索引到循环边界与预取目标寄存器的实际组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins

ROOTS = ("u_ctrl.l2_idx", "u_ctrl.w_group_idx")
TARGETS = ("u_ctrl.pf_r_target", "u_ctrl.w_cur_r",
           "u_ctrl.is_last_l2_group", "u_ctrl.is_last_w_group")


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
        "register_groups": {},
    }
    for signal in ROOTS:
        def selected(name, cell, port):
            origin = cell.get("attributes", {}).get("fpga_register_origin") or ""
            return origin == signal or origin.startswith(signal + " [")

        paths = connected_paths(module, limit=100000, group_limit=100000, root_filter=selected)
        if not paths["graph_complete"]:
            raise RuntimeError("Mapped IA connectivity graph is incomplete")
        targets = {}
        for target in TARGETS:
            matches = [path for path in paths["register_to_register_paths"]
                       if (path["endpoint"].get("register_origin") or "").split(" [")[0] == target]
            targets[target] = {
                "connected": bool(matches),
                "longest_path_cells": max((path["combinational_cells"] for path in matches), default=0),
                "longest_paths": matches[:1],
            }
        result["register_groups"][signal] = targets
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({signal: {target: data["longest_path_cells"] if data["connected"] else None
                               for target, data in targets.items()}
                      for signal, targets in result["register_groups"].items()}))


if __name__ == "__main__":
    main()
