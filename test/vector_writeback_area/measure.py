#!/usr/bin/env python3
"""在相同 xc7 综合设置下比较向量写回模块的资源与组合深度。"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_writeback.sv")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="4dee27ffec4dc891daf2681379f8b3fd27fd41f2")
    parser.add_argument("--out", type=Path, default=ROOT / "build/vector_writeback_measurement")
    parser.add_argument("--lock-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = out / "inputs"
    (inputs / "rtl/common").mkdir(parents=True, exist_ok=True)
    (inputs / "include").mkdir(exist_ok=True)
    reference_text = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"],
                                             cwd=ROOT, text=True)
    (inputs / "reference.sv").write_text(reference_text)
    (inputs / "current.sv").write_bytes((ROOT / SOURCE).read_bytes())
    source_hash = digest(ROOT / SOURCE)
    options = ["-GTILE=16", "-GBUS_WIDTH=64", "-D", "SYNTHESIS=1", "-D", "XILINX_FPGA=1"]
    cases = {
        "reference": dict(top="vector_writeback", sources=["reference.sv"], options=options,
                          configuration="16 result lanes, 64-bit bus, general coalescing"),
        "current": dict(top="vector_writeback", sources=["current.sv"],
                        options=options + ["-Gp_coalesce_bytes_only=1"],
                        configuration="16 result lanes, 64-bit bus, vector-engine byte coalescing"),
    }
    config = inputs / "cases.json"
    config.write_text(json.dumps(cases, indent=2) + "\n")
    command = [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
               "--source-root", str(inputs), "--case-config", str(config),
               "--cases", "reference", "current", "--out", str(out / "synthesis")]
    if args.lock_file:
        command += ["--lock-file", str(args.lock_file.resolve())]
    subprocess.run(command, cwd=ROOT, check=True)
    if source_hash != digest(ROOT / SOURCE):
        raise RuntimeError("综合期间源文件发生变化")
    summary = json.loads((out / "synthesis/summary.json").read_text())
    fields = ("lut_cells", "flip_flops", "ramb36", "ramb18", "dsp",
              "longest_register_path_cells", "longest_combinational_path_cells")
    report = dict(scope="Independent module synthesis and mapped cell connectivity",
                  tool=summary["tool"], part=summary["part"], family=summary["family"],
                  reference_commit=args.reference,
                  reference_sha256=hashlib.sha256(reference_text.encode()).hexdigest(),
                  source_sha256=source_hash,
                  reference={name: summary["cases"]["reference"][name] for name in fields},
                  current={name: summary["cases"]["current"][name] for name in fields},
                  command=command)
    (out / "measurement.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
