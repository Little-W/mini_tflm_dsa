#!/usr/bin/env python3
"""使用独立历史定义证明权重加载器的完整状态和公开输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/kernel_prefetch"))
from run_reference_comparison import prepare_reference

PROFILES = (
    dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, DMA_LANES=8, COUNT_WIDTH=29),
    dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=128, DMA_LANES=16, COUNT_WIDTH=32),
    dict(SIZE=4, DATA_WIDTH=8, BUS_WIDTH=32, DMA_LANES=4, COUNT_WIDTH=8),
    dict(SIZE=6, DATA_WIDTH=16, BUS_WIDTH=24, DMA_LANES=3, COUNT_WIDTH=7),
    dict(SIZE=4, DATA_WIDTH=8, BUS_WIDTH=8, DMA_LANES=1, COUNT_WIDTH=8),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="f468ca5d")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference, _, manifest = prepare_reference(args.reference, out)
    resolve = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolve([ROOT / "rtl/npu/loaders/kernel_loader.sv"], ROOT)
    source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    snapshots = []
    for path in sources:
        target = out / "current" / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        snapshots.append(target)
    records = []
    for index, profile in enumerate(PROFILES):
        parameters = dict(profile, REG_WIDTH=32, CACHE_BLOCKS=1)
        folder = out / f"profile_{index}"
        folder.mkdir(exist_ok=True)
        commands = []
        for label, top, files in (
            ("reference", "kernel_ref__kernel_loader", [reference]),
            ("current", "kernel_loader", snapshots),
        ):
            options = " ".join(f"-G{name}={value}" for name, value in parameters.items())
            commands += [
                f"read_slang --top {top} -DSYNTHESIS=1 -DXILINX_FPGA=1 {options} " + " ".join(map(str, files)),
                "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                f"prep -top {top} -flatten", "memory_map", "async2sync", "opt_clean",
                f"rename {top} {label}", f"design -stash {label}",
            ]
        commands += [
            "design -copy-from reference -as reference reference",
            "design -copy-from current -as current current",
            "equiv_make reference current equivalent", "hierarchy -top equivalent",
            "equiv_simple -short -seq 1", "opt_clean", "equiv_induct -seq 2",
            "equiv_status -assert",
        ]
        script, log = folder / "proof.ys", folder / "proof.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=900)
        match = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", log.read_text())
        if result.returncode or match is None or int(match[2]):
            raise RuntimeError(str(log))
        record = dict(parameters=parameters, passed=True, equivalent_bits=int(match[1]),
                      script_sha256=digest(script), log_sha256=digest(log))
        records.append(record)
        print(json.dumps(record), flush=True)
    if source_hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError("验证期间 RTL 源文件发生变化")
    summary = dict(passed=True, inputs_constrained=False, reference=manifest,
                   source_sha256=source_hashes, profiles=records,
                   equivalent_bits=sum(record["equivalent_bits"] for record in records))
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
