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
    "rtl/npu/top/npu_matrix_engine.sv",
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
        source_root = Path(manifest.get("source_root", ROOT)).resolve()
        for relative in CAPACITY_SOURCES:
            if manifest["source_sha256"].get(relative) != digest(source_root / relative):
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


def capacity_profile(manifest):
    """根据已构建程序的参数计算输入复用和权重窗口的有效范围。"""
    required = ("size", "shared_bank_bytes", "shared_bank_count", "ia_compact_enable",
                "ps_frame_count", "ps_storage_rows", "oa_s16_fifo_banks_max")
    for name in required:
        if name not in manifest:
            raise RuntimeError("Simulator capacity parameter is missing: " + name)
    if manifest["ia_compact_enable"] not in (0, 1):
        raise RuntimeError("Simulator IA_COMPACT_ENABLE must be zero or one")
    if manifest["ps_frame_count"] < 1:
        raise RuntimeError("Simulator PS_FRAME_COUNT must be positive")
    size = manifest["size"]
    bank_bytes = manifest["shared_bank_bytes"]
    bank_count = manifest["shared_bank_count"]
    max_ia_banks = 4 if bank_count >= 8 else 2
    block_bytes = size * size * 2
    blocks_per_bank = bank_bytes // block_bytes
    compact = bool(manifest["ia_compact_enable"])
    return {
        **{name: manifest[name] for name in required},
        **{name: manifest[name] for name in ("address_width", "vector_pe_count") if name in manifest},
        "ia_block_bytes": block_bytes,
        "ia_blocks_per_bank": blocks_per_bank,
        "maximum_ia_banks": max_ia_banks,
        "maximum_ia_reuse": max_ia_banks * blocks_per_bank // (1 if compact else 2),
        "maximum_w_reuse": manifest["ps_frame_count"],
        "maximum_frame_rows": size * max_ia_banks * blocks_per_bank // (1 if compact else 2),
        "physical_bank_words": bank_bytes // 16,
        "matrix_requant_compute_lanes": 2 if bank_count < 8 and size > 2 and size % 2 == 0 else size,
        "minimum_noncompact_ia_banks": 2,
        "formulas": {
            "ia_blocks_per_bank": "shared_bank_bytes / (size * size * 2)",
            "active_compact": "ia_compact_enable and (dataflow == IS or lhs_dtype == INT8)",
            "input_reuse_limit": "ia_banks * ia_blocks_per_bank / (active_compact ? 1 : 2)",
            "maximum_w_reuse": "ps_frame_count",
            "maximum_frame_rows": "maximum_ia_reuse * size",
            "frame_rows_limit": "min(maximum_frame_rows, floor(ps_banks * floor(physical_bank_words / frames) / 4))",
        },
    }


def input_limits(profile, mode, wide, banks):
    """IS 流式输入为 INT8 权重；WS 流式输入使用左操作数的实际位宽。"""
    compact = bool(profile["ia_compact_enable"] and (mode or not wide))
    minimum_banks = 1 if compact else profile["minimum_noncompact_ia_banks"]
    maximum_reuse = banks * profile["ia_blocks_per_bank"] // (1 if compact else 2)
    return compact, minimum_banks, min(maximum_reuse, profile["maximum_ia_reuse"])


def capacity_cases(profile):
    """保留数值尺寸与错误类别，并按实际存储配置补充复用上下界检查。"""
    cases = []

    def append(name, mode, banks, r, w, control, rows, reduction=35, wide=False,
               error=0, category="numeric", adapt=False):
        # 数值矩阵尺寸使用原始窗口大小；硬件窗口缩小时增加分组次数。
        columns = profile["size"] * w + 3
        if adapt:
            _, minimum_banks, _ = input_limits(profile, mode, wide, banks)
            banks = max(banks, minimum_banks)
            _, _, maximum_reuse = input_limits(profile, mode, wide, banks)
            r = min(r, maximum_reuse)
            w = min(w, profile["maximum_w_reuse"])
        compact, minimum_banks, maximum_reuse = input_limits(profile, mode, wide, banks)
        cases.append(dict(name=name, mode=mode, banks=banks, r=r, w=w, control=control,
                          stream_rows=rows, stream_columns=columns, reduction=reduction,
                          wide=wide, expected_error=error, category=category,
                          active_compact=compact, minimum_ia_banks=minimum_banks,
                          maximum_input_reuse=maximum_reuse))

    for mode in (0, 1):
        flow = "is" if mode else "ws"
        for index, (banks, r, w, control, rows, reduction) in enumerate((
                (1, 16, 2, 0, 21, 35),
                (2, 32, 5, 0, 515, 35),
                (2, 32, 16, 14, 37, 35),
                (2, 8, 3, 10, 133, 35),
                (1, 8, 1, 6, 129, 35),
                (2, 32, 2, 1, 517, 16))):
            append(f"{flow}_capacity_{index}", mode, banks, r, w, control, rows,
                   reduction, adapt=True)
    append("ws_s16_capacity", 0, 2, 16, 2, 0, 261, wide=True, adapt=True)
    append("is_s16_capacity", 1, 1, 16, 3, 6, 73, wide=True, adapt=True)
    _, minimum_banks, _ = input_limits(profile, 0, False, 1)
    for name, banks, r, w, control, error in (
            ("ia_three", 3, 2, 2, 0, 1), ("ia_four", 4, 2, 2, 0, 1),
            ("ia_range", 9, 2, 2, 0, 1), ("r_three", minimum_banks, 3, 2, 0, 2),
            ("r_range", 2, 64, 2, 0, 2),
            ("w_range", minimum_banks, 2, profile["maximum_w_reuse"] + 1, 0, 1),
            ("control_range", minimum_banks, 2, 2, 48, 1)):
        append("invalid_" + name, 0, banks, r, w, control, 17,
               error=error, category="invalid_" + name)

    for mode in (0, 1):
        flow = "is" if mode else "ws"
        banks = profile["maximum_ia_banks"]
        _, _, maximum_reuse = input_limits(profile, mode, False, banks)
        append(flow + "_r_minimum", mode, banks, 1, 2, 0, 17,
               category="minimum_valid_reuse")
        append(flow + "_r_maximum", mode, banks, maximum_reuse, 2, 0,
               profile["size"] * maximum_reuse + 1, category="maximum_valid_reuse")
        # 非法复用值使保存的容量行数为零，部分和存储返回容量错误。
        append(flow + "_r_zero", mode, banks, 0, 2, 0, 17,
               error=2, category="zero_reuse")
        append(flow + "_r_above_capacity", mode, banks, maximum_reuse * 2, 2, 0, 17,
               error=2, category="reuse_above_capacity")
        if not profile["ia_compact_enable"]:
            # 单块用例保留合法 r，独立检查非紧凑输入需要两个存储块的条件。
            _, _, one_bank_reuse = input_limits(profile, mode, False, 1)
            append(flow + "_single_noncompact_bank", mode, 1, one_bank_reuse, 2, 0, 17,
                   error=1, category="noncompact_single_bank")
    return cases


def generate_cases(case_root, profile):
    case_root.mkdir(exist_ok=True)
    cases = []
    specifications = capacity_cases(profile)
    memory_bases = (0x1003, 0x20003, 0x40000, 0x58003, 0x48000, 0x50000)
    for spec in specifications:
        rows, columns = spec["stream_rows"], spec["stream_columns"]
        if spec["mode"]:
            rows, columns = columns, rows
        directory = npu.precision_task(case_root, profile["size"], name=spec["name"], rows=rows,
            columns=columns, reduction=spec["reduction"], dataflow=spec["mode"],
            lhs_s16=spec["wide"], memory_bases=memory_bases, expected_error=spec["expected_error"])
        # 零复用用例以合法分组信息为输入，仅把需要拒绝的复用字段置零。
        configure(directory, banks=spec["banks"], r=max(1, spec["r"]), w=spec["w"],
                  control=spec["control"], bank_bytes=profile["shared_bank_bytes"],
                  bank_count=profile["shared_bank_count"])
        if spec["r"] == 0:
            config_path = directory / "config.mem"
            words = config_path.read_text().split()
            words[6] = "00000000"
            config_path.write_text("\n".join(words) + "\n")
        metadata_path = directory / "case.json"
        metadata = json.loads(metadata_path.read_text())
        metadata["shared_memory"]["r"] = spec["r"]
        metadata["capacity_test"] = spec
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        cases.append(directory)
    return cases, specifications


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
    sim = (args.sim or args.reference_sim or (out / "sim")).resolve()
    if args.sim or args.reference_sim:
        binary, manifest = validated_simulator(sim, args.bus_width, bool(args.sim))
    else:
        binary, manifest = build_simulator(sim, args.verilator, args.jobs, args.bus_width)
    profile = capacity_profile(manifest)
    cases, specifications = generate_cases(out / "cases", profile)
    result = npu.run_suite(binary, out, "capacity", cases, no_random=False,
                           timeout=args.suite_timeout)
    measurements = result["measurements"]
    summary = {"passed": result["passed"] and len(measurements) == len(cases), "bus_width": args.bus_width,
               "shared_bank_bytes": 8192, "shared_bank_count": 7,
               "force_raw": True,
               "hardware_profile": profile,
               "case_specifications": specifications,
               "cases": len(cases), "completed_cases": len(measurements),
               "int32_checks": sum(row["int32_checks"] for row in measurements),
               "original_case_count": 21,
               "additional_boundary_cases": len(cases) - 21,
               "original_int32_checks": sum(row["int32_checks"] for row in measurements[:21]),
               "boundary_int32_checks": sum(row["int32_checks"] for row in measurements[21:]),
               "expected_error_rules": {
                   "valid_configuration": 0,
                   "noncompact_single_bank": 1,
                   "invalid_allocation_or_control_or_weight_window": 1,
                   "invalid_input_reuse_with_zero_directory_stride": 2,
               },
               "source_sha256": {relative: manifest["source_sha256"][relative]
                                 for relative in CAPACITY_SOURCES if relative in manifest["source_sha256"]},
               "capacity_observer_sha256": manifest["source_sha256"].get(str(OBSERVER.relative_to(ROOT))),
               "validation_scope": "case_expectations" if args.reference_sim else "capacity_rtl",
               "embedded_capacity_assertions": str(OBSERVER.relative_to(ROOT)) in manifest["source_sha256"],
               "suite_timeout_seconds": args.suite_timeout,
               "simulator_manifest": str(sim / "build.json"), "suite": result}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ("suite", "source_sha256", "case_specifications")}))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
