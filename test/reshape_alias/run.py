#!/usr/bin/env python3
"""Validate reshape storage sharing through the production TFLM allocator."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TFLM = ROOT / "drivers/tflm/tflm/tflite-micro"
MICRO = TFLM / "tensorflow/lite/micro"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/reshape_alias")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [Path(__file__).with_name("test_alias.cc")]
    sources += [MICRO / name for name in (
        "micro_allocator.cc", "micro_allocation_info.cc", "memory_helpers.cc",
        "flatbuffer_utils.cc", "micro_log.cc",
        "debug_log.cc", "tflite_bridge/micro_error_reporter.cc",
        "arena_allocator/single_arena_buffer_allocator.cc",
        "arena_allocator/persistent_arena_buffer_allocator.cc",
        "arena_allocator/non_persistent_arena_buffer_allocator.cc",
        "memory_planner/greedy_memory_planner.cc",
        "memory_planner/linear_memory_planner.cc",
        "tflite_bridge/flatbuffer_conversions_bridge.cc",
    )]
    sources += [TFLM / "tensorflow/lite/core/api/flatbuffer_conversions.cc",
                TFLM / "tensorflow/lite/core/c/common.cc",
                TFLM / "tensorflow/compiler/mlir/lite/schema/schema_utils.cc"]
    downloads = MICRO / "tools/make/downloads"
    command = ["g++", "-std=c++17", "-O1", "-g", "-fno-exceptions", "-Wall", "-Wextra",
               "-Wno-unused-parameter", "-ffunction-sections", "-fdata-sections",
               "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
               "-DTF_LITE_STATIC_MEMORY", "-DTF_LITE_DISABLE_X86_NEON",
               "-DTF_LITE_STRIP_ERROR_STRINGS", "-I", str(TFLM),
               "-I", str(downloads / "flatbuffers/include"),
               "-I", str(downloads / "gemmlowp"),
               *map(str, sources), "-Wl,--gc-sections", "-o", str(out / "test_alias")]
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sources + [MICRO / "micro_allocation_info.h"]}
    build = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    (out / "build.log").write_text("COMMAND: " + " ".join(command) + "\n" + build.stdout + build.stderr)
    if build.returncode:
        print(build.stdout + build.stderr)
        return build.returncode
    result = subprocess.run([str(out / "test_alias")], cwd=ROOT, text=True,
                            capture_output=True, timeout=60,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    (out / "run.log").write_text(result.stdout + result.stderr)
    passed = result.returncode == 0 and "RESHAPE_ALIAS_PASS" in result.stdout
    report = {"passed": passed, "build_command": command,
              "source_sha256": before,
              "verification": "Production allocator, ASan/UBSan, alias chains, branches, graph outputs, nonmonotonic tensor indices, repeated inference, immutable lifetimes, linear/offline/multiple-subgraph behavior, constants, variables, type/size differences and multiple producers",
              "result": result.stdout.strip()}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(result.stdout + result.stderr, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
