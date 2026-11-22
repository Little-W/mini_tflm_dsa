#!/usr/bin/env python3
"""使用同一组公共 RTL 和综合参数测量完整权重加载器的资源与组合深度。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source

LOADERS = ("kernel_loader.sv", "kernel_loader_ctrl.sv", "kernel_loader_buffer.sv")
PARAMETERS = {"SIZE": 16, "REG_WIDTH": 32, "COUNT_WIDTH": 29,
              "DATA_WIDTH": 16, "BUS_WIDTH": 64}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = out / "source"
    (source / "include").mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "rtl/npu/loaders" / name for name in LOADERS]
    paths += sorted((ROOT / "rtl/common").glob("*.sv"))
    paths += sorted((ROOT / "rtl/common").glob("*.v"))
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in paths}
    for path in paths:
        if path.parent.name != "common":
            continue
        target = source / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    cases = {}
    reference_hashes = {}
    for label in ("reference", "current"):
        folder = source / label
        folder.mkdir(exist_ok=True)
        for name in LOADERS:
            relative = "rtl/npu/loaders/" + name
            content = (read_rtl_source(f"{args.reference}:{relative}", cwd=ROOT)
                       if label == "reference" else (ROOT / relative).read_bytes())
            (folder / name).write_bytes(content)
            if label == "reference":
                reference_hashes[relative] = hashlib.sha256(content).hexdigest()
        cases[label] = {
            "top": "kernel_loader",
            "options": ["-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"] +
                       [f"-G{name}={value}" for name, value in PARAMETERS.items()],
            "sources": [str((folder / name).relative_to(source)) for name in LOADERS],
            "configuration": "生产配置的完整权重加载器",
        }
    config = out / "cases.json"
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(source), "--case-config", str(config),
               "--cases", "reference", "current", "--out", str(out / "synthesis"),
               "--max-register-path-cells", "10"]
    subprocess.run(command, cwd=ROOT, check=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in paths}:
        raise RuntimeError("测量期间 RTL 源文件发生变化")
    report = {"reference": args.reference, "parameters": PARAMETERS,
              "source_sha256": hashes, "reference_sha256": reference_hashes,
              "synthesis_command": command, "cases": {}}
    for label in cases:
        folder = out / "synthesis" / label
        metrics = json.loads((folder / "metrics.json").read_text())
        if not metrics["paths"]["graph_complete"]:
            raise RuntimeError(f"{label} 的连接图不完整")
        report["cases"][label] = {
            "resources": metrics["resources"],
            "longest_register_path_cells": metrics["paths"]["longest_register_path_cells"],
            "graph_complete": True,
            "metrics_sha256": digest(folder / "metrics.json"),
            "manifest_sha256": digest(folder / "manifest.json"),
        }
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
