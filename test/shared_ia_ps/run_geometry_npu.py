#!/usr/bin/env python3
"""Exercise 8 KiB banks and maximum IA reuse through the complete NPU."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from run_shared_npu import configure, npu
from run_packed_shared import pack_operand


def generate(out: Path, bank_count: int) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    memory_bases = (0x1003, 0x20003, 0x40000, 0x58003, 0x48000, 0x50000)

    def gemm(name, mode, banks, r, w, red, *, wide=False, control=0, packed=False):
        stream_rows, stream_cols = 16 * r + 5, 16 * w + 3
        rows, cols = (stream_cols, stream_rows) if mode else (stream_rows, stream_cols)
        directory = npu.precision_task(out, 16, name=name, rows=rows,
            columns=cols, reduction=red, dataflow=mode, lhs_s16=wide,
            memory_bases=memory_bases)
        configure(directory, banks=banks, r=r, w=w, control=control,
                  bank_bytes=8192, bank_count=bank_count)
        if packed:
            pack_operand(directory, "lhs")
            pack_operand(directory, "rhs")
        cases.append(directory)

    for mode in (0, 1):
        flow = "is" if mode else "ws"
        for banks, r in ((1, 16), (2, 32), (4, 64)):
            gemm(f"single_s8_{flow}_b{banks}_r{r}", mode, banks, r, 2, 16,
                 control=1)
        gemm(f"single_s16_{flow}_r32", mode, 4, 32, 2, 16, wide=True,
             control=1, packed=True)
        for banks, r in ((1, 8), (2, 16)):
            gemm(f"raw_multi_{flow}_b{banks}", mode, banks, r, 1, 35,
                 control=1)
        adaptive_banks = 4 if bank_count >= 7 else 2
        adaptive_r = 16 * adaptive_banks
        gemm(f"adaptive_multi_{flow}_r{adaptive_r}", mode, adaptive_banks,
             adaptive_r, 2, 35, control=6)
        gemm(f"packed_multi_{flow}_r32", mode, 2, 32, 3, 35,
             control=6, packed=True)

    reference = npu.make_reference(out)
    for mode in (0, 1):
        directory = npu.task(out, 16, reference, name=f"conv_single_r64_mode{mode}",
            h=5 if mode else 33, w=7 if mode else 33, c=3,
            co=1031 if mode else 35, kh=1, kw=1, ph=0, pw=0, offset=0,
            qmult_base=0x34000, qshift_base=0x38000, dataflow=mode,
            requested_r=2, requested_w=2, seed=12591)
        cases.append(configure(directory, banks=4, r=64, w=2, control=1,
                               bank_bytes=8192, bank_count=bank_count))
    return cases


def validate_sim(directory: Path, bus_width: int, bank_count: int) -> Path:
    manifest = json.loads((directory / "build.json").read_text())
    expected = dict(returncode=0, size=16, bus_width=bus_width,
                    shared_bank_bytes=8192, shared_bank_count=bank_count,
                    ps_compress=True, force_raw=False,
                    pool_bytes=(bank_count - 1) * 8192)
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"Simulator {key} differs from {value}")
    for relative, expected_hash in manifest["source_sha256"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected_hash:
            raise RuntimeError(f"Simulator source changed: {relative}")
    binary = directory / "obj/Vtb_conv_npu"
    if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["binary_sha256"]:
        raise RuntimeError("Simulator executable differs from its manifest")
    return binary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sim", type=Path)
    parser.add_argument("--bank-count", type=int, choices=range(6, 10), default=7)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--jobs", type=int, default=1)
    parser.add_argument("--verilator", default="verilator")
    args = parser.parse_args()
    out = args.out.resolve()
    cases = generate(out / "cases", args.bank_count)
    sim = args.sim.resolve() if args.sim else out / "sim"
    if args.sim is None:
        npu.build(sim, 16, args.verilator, args.jobs, ps_compress=True,
                  pool_bytes=(args.bank_count - 1) * 8192, bus_width=args.bus_width,
                  shared_bank_bytes=8192, shared_bank_count=args.bank_count)
    binary = validate_sim(sim, args.bus_width, args.bank_count)
    suites = []
    for name, fixed in (("fixed", True), ("random", False)):
        result = npu.run_suite(binary, out, name, cases, no_random=fixed)
        for directory, measured in zip(cases, result["measurements"]):
            selected = json.loads((directory / "case.json").read_text())["shared_memory"]
            result["passed"] &= (
                measured["ia_bytes"] == selected["ia_banks"] * 8192 and
                measured["ps_bytes"] == selected["ps_banks"] * 8192 and
                measured["int32_checks"] > 0)
        suites.append(result)
        if not result["passed"]:
            break
    summary = dict(passed=all(item["passed"] for item in suites),
        bus_width=args.bus_width, shared_bank_bytes=8192,
        shared_bank_count=args.bank_count, expected_cases=2 * len(cases),
        completed_cases=sum(len(item["measurements"]) for item in suites),
        int32_checks=sum(row["int32_checks"] for item in suites for row in item["measurements"]),
        source_sha256={str(Path(__file__).relative_to(ROOT)):
                       hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        simulator_manifest=str(sim / "build.json"), suites=suites)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("SHARED_GEOMETRY_NPU_RESULT", summary["passed"],
          summary["completed_cases"], summary["int32_checks"], flush=True)
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
