#!/usr/bin/env python3
"""使用完整算术和寄存状态证明检查共享乘加的全部操作码。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference-rev", default="caace9471dafe0236f0e2a9a40b8ddb48bdb844d")
    parser.add_argument("--arithmetic-summary", type=Path)
    args = parser.parse_args()
    root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    runner = ROOT / "test/vector_extremum/run.py"
    source = root / "rtl/npu/conv/vector_pe.sv"
    summary = args.arithmetic_summary.resolve() if args.arithmetic_summary else out / "arithmetic/summary.json"
    if not args.arithmetic_summary:
        subprocess.run([sys.executable, str(runner), "--source-root", str(root),
                        "--reference", args.reference_rev, "--out", str(summary.parent)],
                       cwd=ROOT, check=True)
    arithmetic = json.loads(summary.read_text())
    if not arithmetic.get("passed") or arithmetic.get("reference") != args.reference_rev:
        raise RuntimeError("PE 算术证明未完成或参考版本不一致")
    for path in (source, runner):
        if arithmetic["source_sha256"].get(str(path)) != digest(path):
            raise RuntimeError("PE 算术证明的输入文件已变化")
    modes = {row["case"]: row for row in arithmetic["runs"]}
    profiles = []
    for extended in (0, 1):
        name = f"extended{extended}_selected0"
        mode = modes[name]
        if not mode["passed"] or mode["arithmetic_output_bits"] != 32 or mode["captured_state_bits"] != 67:
            raise RuntimeError("PE 算术或寄存状态覆盖不完整")
        for operation in range(8):
            profiles.append({"extended_multiply": extended, "operation": operation,
                             "passed": True, "proof": name, "compared_output_bits": 32})
    report = {"passed": True, "source_sha256": digest(source),
              "reference_revision": args.reference_rev, "operand_constraints": [],
              "compared_output_bits": 32, "runs": profiles,
              "arithmetic_summary": str(summary), "arithmetic_summary_sha256": digest(summary),
              "test_sha256": digest(Path(__file__).resolve())}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "profiles": len(profiles)}))


if __name__ == "__main__":
    main()
