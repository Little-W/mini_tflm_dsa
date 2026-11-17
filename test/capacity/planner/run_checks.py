#!/usr/bin/env python3
"""Run portable planner equivalence checks with undefined-behavior detection."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
TESTS = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/planner/native")
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = [ROOT / "drivers/gempact_tiling.h", *sorted(TESTS.glob("*.c")), Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    compiler = Path(shutil.which(args.cc) or args.cc).resolve()
    records = []
    started = time.monotonic()
    for name, sources in (("equivalence", ["test_equivalence.c", "reference_plan.c"]),
                          ("exhaustive", ["test_device_planner.c"]),
                          ("literal_capacity", ["test_literal_capacity.c"]),
                          ("geometry", ["test_geometry.c"]),
                          ("shared", ["test_shared.c"])):
        binary = out / name
        command = [str(compiler), "-std=c11", "-O1", "-g0", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all", "-DDSA_MMIO_CUSTOM=1", "-I" + str(ROOT / "drivers"),
                   *[str(TESTS / p) for p in sources], "-o", str(binary)]
        result = subprocess.run(command, text=True, capture_output=True)
        (out / (name + "_compile.log")).write_text(result.stdout + result.stderr)
        result.check_returncode()
        result = subprocess.run([str(binary)], text=True, capture_output=True)
        (out / (name + ".log")).write_text(result.stdout + result.stderr)
        result.check_returncode()
        report = json.loads(result.stdout.splitlines()[-1])
        assert report["passed"]
        records.append({"name": name, **report, "compile_command": command,
                        "binary_sha256": sha(binary), "log_sha256": sha(out / (name + ".log"))})
    assert hashes == {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    report = {"passed": True, "tests": records, "source_sha256": hashes,
              "compiler_sha256": sha(compiler), "undefined_behavior_sanitizer": True,
              "frame_counts": [1, 4, 8, 16, 25, 32, 64], "elapsed_seconds": time.monotonic() - started}
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": True, "report": str(out / "summary.json")}))


if __name__ == "__main__":
    main()
