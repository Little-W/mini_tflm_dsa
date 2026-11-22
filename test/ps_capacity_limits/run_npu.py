#!/usr/bin/env python3
"""在共享存储完整 NPU 中检查容量判定、错误状态和量化数值。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from run_shared_npu import configure, npu

CAPACITY_SOURCES = (
    "rtl/npu/top/npu_top.sv",
    "rtl/npu/top/npu_task_configuration.sv",
    "rtl/npu/control/ps_capacity_limits.sv",
)
OBSERVER = Path(__file__).resolve().parent / "npu_capacity_observer.sv"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validated_simulator(sim, bus_width, require_current_sources):
    manifest = json.loads((sim / "build.json").read_text())
    expected = {"returncode": 0, "size": 16, "bus_width": bus_width,
                "shared_bank_bytes": 8192, "shared_bank_count": 7,
                "ps_compress": True, "force_raw": True, "pool_bytes": 49152}
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"Simulator {key} differs from {value}")
    binary = sim / "obj/Vtb_conv_npu"
    if digest(binary) != manifest["binary_sha256"]:
        raise RuntimeError("Simulator executable differs from its manifest")
    if require_current_sources:
        for relative in CAPACITY_SOURCES:
            if manifest["source_sha256"].get(relative) != digest(ROOT / relative):
                raise RuntimeError("Simulator capacity RTL differs: " + relative)
    return binary, manifest


def build_simulator(sim, verilator_name, jobs, bus_width):
    verilator = shutil.which(verilator_name)
    if not verilator:
        raise RuntimeError("Cannot locate Verilator: " + verilator_name)
    source_files = npu.source_files

    def observed_sources(source_root):
        sources, includes, tracked = source_files(source_root)
        return [*sources, OBSERVER], includes, [*tracked, OBSERVER]

    # 观察器与生产模块分别编译，构建清单同时记录观察器的文件摘要。
    npu.source_files = observed_sources
    try:
        binary = npu.build(sim, 16, verilator, jobs, ps_compress=True,
                           force_raw=True, pool_bytes=49152, bus_width=bus_width,
                           shared_bank_bytes=8192, shared_bank_count=7)
    finally:
        npu.source_files = source_files
    return binary, json.loads((sim / "build.json").read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--suite-timeout", type=int, default=900)
    parser.add_argument("--bus-width", type=int, choices=(32, 64), default=64)
    reuse = parser.add_mutually_exclusive_group()
    reuse.add_argument("--sim", type=Path, help="reuse a simulator with matching capacity RTL")
    reuse.add_argument("--reference-sim", type=Path, help="validate cases with an existing production simulator")
    args = parser.parse_args()
    if args.suite_timeout <= 0:
        parser.error("--suite-timeout must be positive")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    case_root = out / "cases"
    case_root.mkdir(exist_ok=True)
    cases = []
    memory_bases = (0x1003, 0x20003, 0x40000, 0x58003, 0x48000, 0x50000)

    def gemm(name, mode, banks, r, w, control, rows, reduction=35, wide=False, error=0):
        stream_columns = 16*w + 3
        actual_rows, actual_columns = (stream_columns, rows) if mode else (rows, stream_columns)
        directory = npu.precision_task(case_root, 16, name=name, rows=actual_rows,
            columns=actual_columns, reduction=reduction, dataflow=mode, lhs_s16=wide,
            memory_bases=memory_bases, expected_error=error)
        cases.append(configure(directory, banks=banks, r=r, w=w, control=control,
                               bank_bytes=8192, bank_count=7))

    for mode in (0, 1):
        flow = "is" if mode else "ws"
        for index, (banks, r, w, control, rows, reduction) in enumerate((
                (1, 16, 2, 0, 21, 35),
                (2, 32, 5, 0, 515, 35),
                (2, 32, 16, 14, 37, 35),
                (2, 8, 3, 10, 133, 35),
                (1, 8, 1, 6, 129, 35),
                (2, 32, 2, 1, 517, 16))):
            gemm(f"{flow}_capacity_{index}", mode, banks, r, w, control, rows, reduction)
    gemm("ws_s16_capacity", 0, 2, 16, 2, 0, 261, wide=True)
    gemm("is_s16_capacity", 1, 1, 16, 3, 6, 73, wide=True)
    for name, banks, r, w, control, error in (
            ("ia_three", 3, 2, 2, 0, 1), ("ia_four", 4, 2, 2, 0, 1),
            ("ia_range", 9, 2, 2, 0, 1), ("r_three", 1, 3, 2, 0, 2),
            ("r_range", 2, 64, 2, 0, 2), ("w_range", 1, 2, 17, 0, 1),
            ("control_range", 1, 2, 2, 48, 1)):
        gemm("invalid_" + name, 0, banks, r, w, control, 17, error=error)
    sim = (args.sim or args.reference_sim or (out / "sim")).resolve()
    if args.sim or args.reference_sim:
        binary, manifest = validated_simulator(sim, args.bus_width, bool(args.sim))
    else:
        binary, manifest = build_simulator(sim, args.verilator, args.jobs, args.bus_width)
    result = npu.run_suite(binary, out, "capacity", cases, no_random=False,
                           timeout=args.suite_timeout)
    measurements = result["measurements"]
    summary = {"passed": result["passed"], "bus_width": args.bus_width,
               "shared_bank_bytes": 8192, "shared_bank_count": 7,
               "force_raw": True,
               "cases": len(cases), "completed_cases": len(measurements),
               "int32_checks": sum(row["int32_checks"] for row in measurements),
               "source_sha256": {relative: manifest["source_sha256"][relative]
                                 for relative in CAPACITY_SOURCES if relative in manifest["source_sha256"]},
               "capacity_observer_sha256": manifest["source_sha256"].get(str(OBSERVER.relative_to(ROOT))),
               "validation_scope": "case_expectations" if args.reference_sim else "capacity_rtl",
               "embedded_capacity_assertions": str(OBSERVER.relative_to(ROOT)) in manifest["source_sha256"],
               "suite_timeout_seconds": args.suite_timeout,
               "simulator_manifest": str(sim / "build.json"), "suite": result}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ("suite", "source_sha256")}))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
