#!/usr/bin/env python3
"""在共享存储完整 NPU 中检查容量判定、错误状态和量化数值。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "test/ps_compression"))
from run_shared_npu import configure, npu


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
    verilator = shutil.which(args.verilator)
    if not verilator:
        raise RuntimeError("Cannot locate Verilator: " + args.verilator)
    top_path = ROOT / "rtl/npu/top/npu_top.sv"
    source = top_path.read_text()
    comparison = """
        // 测试中保留原始容量表达式，检查实例连接与阶段输入。
        always_ff @(posedge clk) begin
            if (core_rst_n && cfg_stage2_valid && SHARED_RAM_ENABLED &&
                active_ps_bank_count < 32'(SHARED_PHYSICAL_BANKS)) begin
                assert(ps_raw_bank_capacity_fits == (ps_frames_bounded == '0 ||
                    (ps_raw_frame_bank_words <= 64'(4 * IA_REUSE_NUM_MAX * SIZE) &&
                     64'(ps_raw_bank_total) <= 64'(active_ps_bank_depth))))
                    else $fatal(1, "Raw bank capacity differs");
                assert(ps_long_bank_capacity_fits == (ps_frames_bounded == '0 ||
                    (ps_long_frame_bank_words <= 64'(4 * IA_REUSE_NUM_MAX * SIZE) &&
                     64'(ps_long_bank_total) <= 64'(active_ps_bank_depth))))
                    else $fatal(1, "Long bank capacity differs");
                if (cfg_capacity_phase >= 4) begin
                    assert(ps_admission_bank_capacity_fits ==
                        (ps_admission_bank_words <= 64'(active_ps_bank_depth)))
                        else $fatal(1, "Admission bank capacity differs");
                end
            end
        end
"""
    marker = "        wire ps_capacity_config_invalid_calc = (SIZE == 16) &&"
    if source.count(marker) != 1:
        raise RuntimeError("Cannot locate capacity comparison insertion point")
    checked_top = out / "npu_top_checked.sv"
    checked_top.write_text(source.replace(marker, comparison + marker))
    wrapper = out / "verilator_capacity"
    wrapper.write_text("#!" + sys.executable + "\nimport os, sys\n" +
                       "arguments = [" + repr(str(checked_top)) + " if argument == " +
                       repr(str(top_path)) + " else argument for argument in sys.argv[1:]]\n" +
                       "os.execv(" + repr(verilator) + ", [" + repr(verilator) + "] + arguments)\n")
    wrapper.chmod(0o755)

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
        manifest = json.loads((sim / "build.json").read_text())
        expected = {"returncode": 0, "size": 16, "bus_width": args.bus_width,
                    "shared_bank_bytes": 8192, "shared_bank_count": 7,
                    "ps_compress": True, "force_raw": True, "pool_bytes": 49152}
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise RuntimeError(f"Simulator {key} differs from {value}")
        binary = sim / "obj/Vtb_conv_npu"
        if hashlib.sha256(binary.read_bytes()).hexdigest() != manifest["binary_sha256"]:
            raise RuntimeError("Simulator executable differs from its manifest")
        if args.sim:
            for path in (top_path, ROOT / "rtl/npu/control/ps_capacity_limits.sv"):
                if manifest["source_sha256"].get(str(path.relative_to(ROOT))) != hashlib.sha256(path.read_bytes()).hexdigest():
                    raise RuntimeError("Simulator capacity RTL differs: " + str(path))
    else:
        binary = npu.build(sim, 16, str(wrapper), args.jobs,
                           ps_compress=True, force_raw=True, pool_bytes=49152, bus_width=args.bus_width,
                           shared_bank_bytes=8192, shared_bank_count=7)
    result = npu.run_suite(binary, out, "capacity", cases, no_random=False,
                           timeout=args.suite_timeout)
    measurements = result["measurements"]
    summary = {"passed": result["passed"], "bus_width": args.bus_width,
               "shared_bank_bytes": 8192, "shared_bank_count": 7,
               "force_raw": True,
               "cases": len(cases), "completed_cases": len(measurements),
               "int32_checks": sum(row["int32_checks"] for row in measurements),
               "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (top_path, ROOT / "rtl/npu/control/ps_capacity_limits.sv")},
               "checked_top_sha256": hashlib.sha256(checked_top.read_bytes()).hexdigest(),
               "validation_scope": "case_expectations" if args.reference_sim else "capacity_rtl",
               "embedded_capacity_assertions": not (args.sim or args.reference_sim),
               "suite_timeout_seconds": args.suite_timeout,
               "simulator_manifest": str(sim / "build.json"), "suite": result}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({key: value for key, value in summary.items()
                      if key not in ("suite", "source_sha256")}))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
