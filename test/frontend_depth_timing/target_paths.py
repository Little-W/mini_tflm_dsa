#!/usr/bin/env python3
"""保存 DMA 内实际寄存器起终点的完整连接路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def description(name, cell):
    return name + " " + cell.get("attributes", {}).get("fpga_register_origin", "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--top", default="axi_dual_block_dma")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    mapped = folder / "mapped.json"
    module = json.loads(mapped.read_text())["modules"][args.top]
    for name, origin in register_origins(folder / "pre_lut.il").items():
        if name in module["cells"]:
            module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
    profiles = (
        ("prepared_descriptor", None, "u_frontend.prepared_tile_q"),
        ("channel_range", None, "u_frontend.group_range_q"),
        ("image_output_data", None, "fe_output_data"),
        ("saved_fill_comparison", None, "lookup_fill_set_match_q"),
        ("demand_word_match", None, "demand_word_matches_q"),
        ("work_word_match", None, "work_word_matches_q"),
        ("queue_q0_to_demand_word", "u_window_queue.g_descriptor[1].u_value.mem", "demand_word_matches_q"),
        ("queue_q0_to_work_word", "u_window_queue.g_descriptor[1].u_value.mem", "work_word_matches_q"),
    )
    report = {"top": args.top, "mapped_sha256": hashlib.sha256(mapped.read_bytes()).hexdigest(),
              "profiles": {}}
    for label, start, finish in profiles:
        endpoint_bits = {bit for name, net in module["netnames"].items() if finish in name
                         for bit in net["bits"] if isinstance(bit, int)}
        endpoint_cells = {name for name, cell in module["cells"].items()
                          if endpoint_bits.intersection(cell["connections"].get("Q", []))}
        paths = connected_paths(module, limit=1, group_limit=1,
            root_filter=None if start is None else
                lambda name, cell, port, text=start: text in description(name, cell),
            sink_filter=lambda name, cell, port, text=finish, names=endpoint_cells:
                name in names or text in description(name, cell))
        selected = paths["register_to_register_paths"]
        report["profiles"][label] = {
            "start_filter": start, "endpoint_filter": finish,
            "endpoint_named_bits": len(endpoint_bits),
            "connected_path_exists": bool(selected),
            "maximum_cells": paths["longest_register_path_cells"] if selected else None,
            "path": selected[0] if selected else None}
        print(label, report["profiles"][label]["maximum_cells"], flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
