#!/usr/bin/env python3
"""使用相同输入比较偏置 DMA、WS 向量及 IS 标量事务的数值和周期。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "17dda6a11cd55ea470712335f2b5cfcfca4b4bd4"
BENCH = Path("test/bias_loader_reuse/tb_bias_loader_reuse.sv")
FILES = (
    BENCH, Path("rtl/npu/loaders/bias_loader.sv"),
    Path("rtl/npu/loaders/bias_loader_ctrl.sv"), Path("rtl/npu/loaders/bias_loader_buffer.sv"),
    Path("rtl/common/regfile.v"), Path("rtl/common/parallel_prefix_add.sv"),
    Path("rtl/common/parallel_unsigned_compare.sv"), Path("rtl/common/add_equal.sv"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    hashes, results = {}, {}
    for label in ("reference", "current"):
        source_root = out / "numeric_inputs" / label
        hashes[label] = {}
        for name in FILES:
            data = ((ROOT / name).read_bytes() if name == BENCH else
                    subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=ROOT)
                    if label == "reference" else (root / name).read_bytes())
            target = source_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            hashes[label][str(name)] = digest(target)
        folder = out / (label + "_numeric")
        result_path = folder / "result.json"
        reusable = False
        if args.resume and result_path.exists():
            saved = json.loads(result_path.read_text())
            simulator = Path(saved.get("simulator", ""))
            reusable = (saved.get("passed") and saved.get("fpga") and
                        saved.get("source_sha256") == hashes[label] and simulator.is_file() and
                        digest(simulator) == saved.get("simulator_sha256"))
        if not reusable:
            folder.mkdir(parents=True, exist_ok=True)
            command = [sys.executable, str(ROOT / "test/bias_loader_reuse/run.py"),
                       "--repo", str(source_root), "--out", str(folder), "--fpga",
                       "--jobs", str(args.jobs), "--verilator", args.verilator]
            with (out / (label + "_numeric_driver.log")).open("w") as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        results[label] = json.loads(result_path.read_text())
        if not results[label]["passed"]:
            raise RuntimeError(str(result_path))
        print(json.dumps(dict(version=label, passed=True, cases=results[label]["case_count"])), flush=True)
    comparison = runpy.run_path(str(ROOT / "test/bias_registered_residency/compare_reuse.py"))
    report = comparison["compare"](results["reference"], results["current"])
    report["identical_cycle_counts"] = all(row["reference_cycles"] == row["current_cycles"]
                                            for row in report["cases"])
    report["passed"] = report["passed"] and report["identical_cycle_counts"]
    report.update(reference_commit=revision, source_sha256=hashes,
                  result_sha256={label: digest(out / (label + "_numeric") / "result.json")
                                 for label in results})
    (out / "numeric_comparison.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["passed"]:
        raise RuntimeError("偏置数值或周期比较未通过")
    print(json.dumps({key: report[key] for key in
                     ("passed", "case_count", "identical_cycle_counts", "reference_total_cycles",
                      "current_total_cycles")}), flush=True)


if __name__ == "__main__":
    main()
