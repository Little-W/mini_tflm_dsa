#!/usr/bin/env python3
"""证明 IA 加载器的全部公开输出、状态更新和保持行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_current_source, read_rtl_source_group

SOURCES = [Path("rtl/npu/loaders") / (name + ".sv")
           for name in ("ia_loader", "ia_loader_ctrl", "ia_loader_cache_mgr")]
PRODUCTION = dict(SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, DMA_LANES=8,
                  REG_WIDTH=32, COUNT_WIDTH=29, CACHE_BLOCKS=32, COMPACT_S8=1,
                  ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12, PS_FRAME_COUNT=16,
                  p_dma_source_layout=1, p_shared_write_stage=1,
                  p_register_dma_request=1)
CASES = {
    "production": PRODUCTION,
    "full_count": dict(PRODUCTION, COUNT_WIDTH=32),
    "regular": dict(PRODUCTION, COMPACT_S8=0),
    "small_generic": dict(PRODUCTION, BUS_WIDTH=32, DMA_LANES=4, COUNT_WIDTH=8,
                          CACHE_BLOCKS=4, ORDERED_JOB=0, p_dma_source_layout=0,
                          p_shared_write_stage=0, p_register_dma_request=0),
    "wide_generic": dict(PRODUCTION, BUS_WIDTH=128, DMA_LANES=16,
                         CACHE_BLOCKS=4, ORDERED_JOB=0, p_dma_source_layout=0),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="7ddc0d8d")
    parser.add_argument("--cases", nargs="+", choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    common = sorted(path for path in (ROOT / "rtl/common").iterdir()
                    if path.suffix in (".sv", ".v"))
    common.append(ROOT / "rtl/npu/loaders/ia_address_add.sv")
    inputs = [ROOT / relative for relative in SOURCES] + common + [
        ROOT / "rtl/npu/loaders/ia_ordered_coordinate_equal.sv",
        ROOT / "rtl/npu/loaders/ia_ordered_coordinate_same.sv"]
    if (ROOT / "rtl/npu/loaders/ia_row_step_register.sv").exists():
        inputs.append(ROOT / "rtl/npu/loaders/ia_row_step_register.sv")
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in inputs}
    snapshots = {}
    for label in ("reference", "current"):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in SOURCES:
            source = (read_rtl_source_group(f"{args.reference}:{relative}", cwd=ROOT, text=True)
                      if label == "reference" else read_current_source(ROOT / relative))
            path = folder / relative.name
            path.write_text(source)
            snapshots[label].append(path)
    summary = dict(passed=False, input_constraints=False,
                   reference_commit=subprocess.check_output(
                       ["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
                   source_sha256=hashes, runs=[])
    for name in args.cases:
        options = ["--top", "ia_loader", "-DSYNTHESIS=1", "-DXILINX_FPGA=1"]
        options += [f"-G{key}={value}" for key, value in CASES[name].items()]
        commands = []
        for label in ("reference", "current"):
            commands += [shlex.join(["read_slang", *options,
                                    *map(str, snapshots[label] + common)]),
                         "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
                         "prep -top ia_loader -flatten", "memory_map", "async2sync", "opt_clean",
                         f"rename ia_loader {label}", f"design -stash {label}"]
        commands += ["design -copy-from reference -as reference reference",
                     "design -copy-from current -as current current",
                     "equiv_make reference current equivalent", "hierarchy -top equivalent",
                     "equiv_simple -seq 1", "opt_clean", "equiv_induct -seq 2", "equiv_status -assert"]
        script, log = out / f"{name}.ys", out / f"{name}.log"
        script.write_text("\n".join(commands) + "\n")
        with log.open("w") as stream:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                                     "--worker", str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=600)
        content = log.read_text()
        count = re.search(r"Of those cells (\d+) are proven and (\d+) are unproven", content)
        record = dict(name=name, parameters=CASES[name],
                      passed=result.returncode == 0 and "Equivalence successfully proven" in content,
                      equivalent_bits=int(count[1]) if count else None,
                      script_sha256=digest(script), log_sha256=digest(log))
        summary["runs"].append(record)
        summary["passed"] = all(row["passed"] for row in summary["runs"])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(record), flush=True)
        if not record["passed"]:
            raise RuntimeError("IA equivalence did not complete: " + str(log))
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in inputs}:
        raise RuntimeError("RTL changed during formal verification")


if __name__ == "__main__":
    main()
