#!/usr/bin/env python3
"""测量生产参数下完整部分和帧存储的资源及寄存器组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/ps_compact/ps_frame_store.sv")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="9e3e5d6a6f47befe6c86aceacad7999923206458")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(MAX_FRAME_ROWS=256, FRAME_COUNT=16, POOL_BYTES=49152,
                      BANK_BYTES=8192, EXTERNAL_RAM=1, p_fixed_ps_channels=1,
                      DIRECTORY_ROWS=1024, RAM_ADDR_BITS=12)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    current = ROOT / SOURCE
    reference = out / "reference.sv"
    reference.write_bytes(subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT))
    cases, hashes = {}, {}
    for label, path in (("reference", reference), ("current", current)):
        sources = resolve([path], ROOT)
        hashes.update({str(source): digest(source) for source in sources})
        cases[label] = {"top": "ps_frame_store", "sources": list(map(str, sources)),
            "options": ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] +
                       [f"-G{name}={value}" for name, value in parameters.items()],
            "configuration": "16 帧、每帧 256 行、48 KiB 存储池及 1024 行共享目录"}
    case_file = out / "cases.json"
    case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
    subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
        "--case-config", str(case_file), "--cases", "reference", "current",
        "--through", "pre_lut", "--out", str(out / "pre")], cwd=ROOT, check=True)
    report = {"reference_revision": args.reference, "source_sha256": hashes,
              "parameters": parameters, "cases": {}}
    for label in cases:
        mapped = out / "mapped" / label
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/remap_fpga_luts.py"),
            "--source", str(out / "pre" / label), "--out", str(mapped), "--mode", "physical-cost",
            "--delay-target-ps", "6667", "--max-lut-inputs", "8", "--small-lut-area-cost", "1",
            "--discard-abc9-temporaries"], cwd=ROOT, check=True)
        metrics = json.loads((mapped / "metrics.json").read_text())
        if not metrics["paths"]["graph_complete"]:
            raise RuntimeError("部分和存储路径分析不完整")
        report["cases"][label] = {"resources": metrics["resources"], "paths": metrics["paths"]}
    if hashes != {path: digest(Path(path)) for path in hashes}:
        raise RuntimeError("综合测量期间输入文件发生变化")
    (out / "measurement.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
