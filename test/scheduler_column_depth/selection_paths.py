#!/usr/bin/env python3
"""检查调度器帧选择路径与寄存器到公开输出的组合深度。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from support import ROOT

sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def analyze_selection(folder):
    folder = Path(folder)
    module = json.loads((folder / "mapped.json").read_text())["modules"]["ps_window_scheduler"]
    for name, value in register_origins(folder / "pre_lut.il").items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = value

    def origin(cell):
        return cell.get("attributes", {}).get("fpga_register_origin", "")

    def longest(paths):
        entries = paths["register_to_register_paths"]
        return {"cells": paths["longest_register_path_cells"],
                "path": entries[0] if entries else None}

    sources = (("opened_paths", "opened"), ("protected_paths", "protected_valid"),
               ("phase_paths", "phase"), ("frame_open_paths", "frame_open"),
               ("live_paths", "live"), ("cursor_paths", "cursor"))
    report = {section: {} for section, _ in sources}
    report["output_paths"] = {}
    # 帧资格和游标可以同时影响候选索引及状态控制端，分别统计这些完整连接路径。
    for section, source in sources:
        for target in ("all_registers", "phase", "selected_id_q", "frame_k$rdreg",
                       "next_column_tile", "cursor", "live", "resume_valid",
                       "command_buffer_valid"):
            result = connected_paths(
                module, limit=1, group_limit=1,
                root_filter=lambda name, cell, port: origin(cell).split(" ")[0] == source,
                sink_filter=lambda name, cell, port: target == "all_registers" or target in origin(cell),
            )
            report[section][target] = longest(result)

    # 只在内存中的分析对象添加输出终点，标记不属于综合网表或组合路径。
    for output_name, port in module["ports"].items():
        if port["direction"] != "output":
            continue
        sink = "$output$" + output_name
        module["cells"][sink] = {
            "type": "FDRE", "connections": {"D": port["bits"]},
            "port_directions": {"D": "input"},
            "attributes": {"fpga_register_origin": output_name},
        }
        result = connected_paths(module, limit=1, group_limit=1,
                                 sink_filter=lambda name, cell, port: name == sink)
        del module["cells"][sink]
        report["output_paths"][output_name] = longest(result)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_selection(args.folder)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for section, values in report.items():
        print(section, {name: row["cells"] for name, row in values.items()})


if __name__ == "__main__":
    main()
