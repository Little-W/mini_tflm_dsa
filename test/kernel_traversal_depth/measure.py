#!/usr/bin/env python3
"""测量完整权重加载控制器与列计数到重复计数的实际连接路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path("rtl/npu/loaders/kernel_loader_ctrl.sv")
PARAMETERS = {"SIZE": 16, "REG_WIDTH": 32, "COUNT_WIDTH": 29}
sys.path.insert(0, str(ROOT / "scripts/fpga"))
from netlist_metrics import connected_paths, register_origins


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--reference-source", type=Path, default=HERE / "reference_controller.sv")
    parser.add_argument("--out", type=Path, default=ROOT / "build/kernel_traversal_depth/measurement")
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    source_root = out / "inputs"
    (source_root / "include").mkdir(parents=True, exist_ok=True)
    inputs = {"reference": args.reference_source.resolve(), "current": args.candidate.resolve()}
    hashes = {label: digest(path) for label, path in inputs.items()}
    paths = {}
    for label, source in inputs.items():
        path = source_root / label / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
        paths[label] = path
    helpers = [path for path in sorted((ROOT / "rtl/common").rglob("*"))
               if path.suffix in (".v", ".sv")]
    helper_hashes = {str(path.relative_to(ROOT)): digest(path) for path in helpers}
    for source in helpers:
        path = source_root / source.relative_to(ROOT)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source.read_bytes())
    cases = {label: {"top": "kernel_loader_ctrl",
        "options": ["-D", "SYNTHESIS=1"] + [f"-G{name}={value}" for name, value in PARAMETERS.items()],
        "sources": [str(path.relative_to(source_root))],
        "configuration": "完整权重加载控制器，SIZE=16、REG_WIDTH=32、COUNT_WIDTH=29",
    } for label, path in paths.items()}
    config = out / "cases.json"
    config.write_text(json.dumps(cases, indent=2, ensure_ascii=False) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(source_root), "--case-config", str(config),
               "--cases", *cases, "--out", str(out / "synthesis")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    if hashes != {label: digest(path) for label, path in inputs.items()}:
        raise RuntimeError("测量期间控制器源码发生变化")
    if helper_hashes != {str(path.relative_to(ROOT)): digest(path) for path in helpers}:
        raise RuntimeError("测量期间公共模块源码发生变化")
    synthesis = json.loads((out / "synthesis/summary.json").read_text())
    report = {"source_sha256": hashes, "helper_sha256": helper_hashes,
              "parameters": PARAMETERS, "tool": synthesis["tool"], "part": synthesis["part"],
              "method": "synth_xilinx -top kernel_loader_ctrl -family xc7 -noiopad -noclkbuf -flatten",
              "scope": "完整控制器独立综合；路径包含寄存器数据和使能端口",
              "cases": {}}
    for label in inputs:
        folder = out / "synthesis" / label
        metrics = json.loads((folder / "metrics.json").read_text())
        module = json.loads((folder / "mapped.json").read_text())["modules"]["kernel_loader_ctrl"]
        for name, origin in register_origins(folder / "pre_lut.il").items():
            if name in module["cells"]:
                module["cells"][name].setdefault("attributes", {})["fpga_register_origin"] = origin

        def origin(cell):
            return cell.get("attributes", {}).get("fpga_register_origin", "")

        paths = connected_paths(module, limit=8, group_limit=8,
            root_filter=lambda name, cell, port: origin(cell).startswith("load_col_in_group "),
            sink_filter=lambda name, cell, port: origin(cell).startswith("load_repeat "))
        (folder / "column_to_repeat_paths.json").write_text(json.dumps(paths, indent=2) + "\n")
        report["cases"][label] = {
            "resources": metrics["resources"],
            "maximum_register_depth": metrics["paths"]["longest_register_path_cells"],
            "column_to_repeat_depth": paths["longest_register_path_cells"],
            "column_to_repeat_path": paths["register_to_register_paths"][0],
        }
        print(label, "LUT", metrics["resources"]["logic_lut_cells"],
              "maximum", metrics["paths"]["longest_register_path_cells"],
              "column_to_repeat", paths["longest_register_path_cells"], flush=True)
    (out / "measurement.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(out / "measurement.json")


if __name__ == "__main__":
    main()
