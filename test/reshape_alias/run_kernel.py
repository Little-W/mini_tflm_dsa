#!/usr/bin/env python3
"""使用上游 RESHAPE 用例和地址检查器验证准备、复制及形状处理。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
TFLM_PATH = Path("drivers/tflm/tflm/tflite-micro")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/reshape_kernel")
    parser.add_argument("--implementation-root", type=Path, default=ROOT,
                        help="待验证的独立实现目录，默认使用当前仓库")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    implementation = args.implementation_root.resolve() / TFLM_PATH
    tflm = ROOT / TFLM_PATH
    micro = tflm / "tensorflow/lite/micro"
    sources = [implementation / "tensorflow/lite/micro/kernels/reshape.cc"]
    sources += [micro / name for name in (
        "kernels/reshape_test.cc", "kernels/reshape_common.cc",
        "kernels/kernel_runner.cc", "kernels/kernel_util.cc",
        "micro_allocator.cc", "micro_allocation_info.cc", "memory_helpers.cc",
        "flatbuffer_utils.cc", "micro_context.cc", "micro_utils.cc",
        "fake_micro_context.cc", "mock_micro_graph.cc", "test_helpers.cc", "system_setup.cc",
        "micro_log.cc", "debug_log.cc", "tflite_bridge/micro_error_reporter.cc",
        "arena_allocator/single_arena_buffer_allocator.cc",
        "arena_allocator/persistent_arena_buffer_allocator.cc",
        "arena_allocator/non_persistent_arena_buffer_allocator.cc",
        "memory_planner/greedy_memory_planner.cc",
        "memory_planner/linear_memory_planner.cc",
        "tflite_bridge/flatbuffer_conversions_bridge.cc",
    )]
    sources += [tflm / name for name in (
        "tensorflow/lite/core/api/flatbuffer_conversions.cc",
        "tensorflow/lite/core/c/common.cc",
        "tensorflow/lite/kernels/kernel_util.cc",
        "tensorflow/compiler/mlir/lite/schema/schema_utils.cc",
    )]
    downloads = micro / "tools/make/downloads"
    command = ["g++", "-std=c++17", "-O0", "-g", "-fno-exceptions",
               "-Wall", "-Wextra", "-Wno-unused-parameter",
               "-ffunction-sections", "-fdata-sections",
               "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-DTF_LITE_STATIC_MEMORY", "-DTF_LITE_DISABLE_X86_NEON",
               "-I", str(tflm), "-I", str(downloads / "flatbuffers/include"),
               "-I", str(downloads / "gemmlowp"),
               *map(str, sources), "-Wl,--gc-sections", "-o", str(out / "reshape_kernel")]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (out / "build.log").write_text("COMMAND: " + " ".join(command) + "\n" + build.stdout + build.stderr)
    if build.returncode:
        print(build.stdout + build.stderr)
        return build.returncode
    run = subprocess.run([str(out / "reshape_kernel")], cwd=ROOT, text=True,
                         capture_output=True, timeout=60,
                         env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    (out / "run.log").write_text(run.stdout + run.stderr)
    passed = run.returncode == 0 and "ALL TESTS PASSED" in run.stdout + run.stderr
    unchanged = hashes == {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    result = dict(passed=passed and unchanged, source_sha256=hashes,
                  sources_unchanged=unchanged, build_command=command,
                  result=(run.stdout + run.stderr).strip())
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(run.stdout + run.stderr, end="")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
