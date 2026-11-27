#!/usr/bin/env python3
"""综合完整 IA 控制器，统计全部寄存器路径及发送触发输入到数据有效寄存器的路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="9e3e5d6a6f47befe6c86aceacad7999923206458")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = out / "inputs"
    subprocess.run([sys.executable, str(ROOT / "test/ia_completion_depth/prepare.py"),
                    "--reference", args.reference, "--out", str(inputs)], cwd=ROOT, check=True)
    manifest = json.loads((inputs / "manifest.json").read_text())
    cases = json.loads((inputs / "cases.json").read_text())
    subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
        "--case-config", str(inputs / "cases.json"), "--cases", "reference", "current",
        "--through", "pre_lut", "--out", str(out / "pre")], cwd=ROOT, check=True)
    report = {"reference_revision": args.reference, "source_sha256": manifest["source_sha256"],
              "cases": {}}
    for label, case in cases.items():
        mapped = out / "mapped" / label
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/remap_fpga_luts.py"),
            "--source", str(out / "pre" / label), "--out", str(mapped), "--mode", "physical-cost",
            "--delay-target-ps", "6667", "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
            "--discard-abc9-temporaries"], cwd=ROOT, check=True)
        top = case["top"]
        module = json.loads((mapped / "mapped.json").read_text())["modules"][top]
        for name, origin in register_origins(out / "pre" / label / "pre_lut.il", top).items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        # 分析图的虚拟起点仅限定已有输入连接，未加入综合输入或资源统计。
        name = "analysis_send_trigger_input"
        spare_bit = max(bit for cell in module["cells"].values()
                        for bits in cell["connections"].values() for bit in bits
                        if isinstance(bit, int)) + 1
        module["cells"][name] = {"type": "FDRE", "parameters": {},
            "attributes": {"fpga_register_origin": "send_ia_trigger input boundary"},
            "port_directions": {"D": "input", "Q": "output"},
            "connections": {"D": [spare_bit], "Q": module["ports"]["send_ia_trigger"]["bits"]}}

        def trigger_source(cell_name, cell, port):
            return cell_name == name

        def valid_sink(cell_name, cell, port):
            return cell.get("attributes", {}).get("fpga_register_origin", "") == "ia_data_valid"

        paths = connected_paths(module, limit=3, group_limit=3,
                                root_filter=trigger_source, sink_filter=valid_sink)
        if not paths["graph_complete"] or not paths["register_to_register_paths"]:
            raise RuntimeError("IA 发送触发路径分析不完整")
        metrics = json.loads((mapped / "metrics.json").read_text())
        report["cases"][label] = {"parameters": case["parameters"],
            "resources": metrics["resources"],
            "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"],
            "register_path_graph_complete": metrics["paths"]["graph_complete"],
            "send_trigger_to_data_valid_paths": paths}
    for path, expected in manifest["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise RuntimeError("综合测量期间输入文件发生变化")
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
