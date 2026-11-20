#!/usr/bin/env python3
"""统计完整预测器中所有寄存器到配置分块数的连接路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.proof.read_text())
    if not proof["passed"]:
        raise RuntimeError("Configuration round proof must pass before measurement")
    cases = {}
    source = "rtl/npu/dma/cache/conv_next_use_predictor.sv"
    for label, folder, expected in (("reference", args.reference, proof["reference_sha256"]),
                                    ("current", args.current, proof["source_sha256"])):
        summary = json.loads((folder / "summary.json").read_text())
        if summary["source_sha256"][source] != expected:
            raise RuntimeError("Formal and synthesized sources differ")
        module = json.loads((folder / "mapped.json").read_text())["modules"]["conv_next_use_predictor"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin
        paths = connected_paths(module, limit=20, group_limit=20,
            sink_filter=lambda n, c, p: c.get("attributes", {}).get("fpga_register_origin", "").startswith("cfg_blocks_q"))
        if not paths["graph_complete"]:
            raise RuntimeError("Incomplete mapped dependency graph")
        cases[label] = dict(source_sha256=summary["source_sha256"], resources=summary["resources"],
            longest_register_path_cells=summary["paths"]["longest_register_path_cells"],
            config_blocks_paths=paths, mapped_sha256=digest(folder / "mapped.json"),
            pre_lut_sha256=digest(folder / "pre_lut.il"))
    for path, current_hash in cases["current"]["source_sha256"].items():
        if path != source and cases["reference"]["source_sha256"].get(path) != current_hash:
            raise RuntimeError("Additional synthesized source differences require verification")
    report = dict(passed=True, reference_commit=proof["reference_commit"], cases=cases,
                  metrics_tool_sha256=digest(ROOT / "scripts/fpga/netlist_metrics.py"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    for label, case in cases.items():
        print(label, case["config_blocks_paths"]["longest_register_path_cells"])


if __name__ == "__main__":
    main()
