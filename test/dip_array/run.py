#!/usr/bin/env python3
"""Check DiP row timing and matrix products for several array sizes and widths."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_one(out, verilator, size, data_bits, weight_bits):
    directory = out / f"size{size}_s{data_bits}_w{weight_bits}"
    directory.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "rtl/npu/compute/ws_systolic_array.sv",
               ROOT / "rtl/npu/compute/ws_systolic_cell.sv", HERE / "array_test.cpp", Path(__file__).resolve()]
    before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    rules = directory / "compile_rules.mk"
    rules.write_text("%.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n"
                     "$(VK_OBJS_FAST): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_FAST) -c -o $@ $<\n"
                     "$(VK_OBJS_SLOW): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_SLOW) -c -o $@ $<\n"
                     "$(VK_GLOBAL_OBJS): %.o: %.cpp\n\t$(OBJCACHE) $(CXX) $(CXXFLAGS) $(CPPFLAGS) $(OPT_GLOBAL) -c -o $@ $<\n")
    command = [verilator, "--cc", "--exe", "--build", "--assert", "-j", "1", "-Wno-fatal",
               "--top-module", "ws_systolic_array", "--Mdir", str(directory / "obj"),
               f"-GSIZE={size}", f"-GDATA_IN_WIDTH={data_bits}", f"-GWEIGHT_WIDTH={weight_bits}",
               "--output-groups", "0", "--output-split", "10000", "-CFLAGS",
               f"-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all -DTEST_SIZE={size} "
               f"-DTEST_DATA_BITS={data_bits} -DTEST_WEIGHT_BITS={weight_bits}",
               "-LDFLAGS", "-fsanitize=undefined", "-MAKEFLAGS",
               f"OPT_FAST=-O1 OPT_SLOW=-O0 OPT_GLOBAL=-O0 VM_DEFAULT_RULES=0 -f {rules}",
               *map(str, sources[:3])]
    with (directory / "compile.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"Compilation failed: {directory / 'compile.log'}")
    binary = directory / "obj/Vws_systolic_array"
    result = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
    (directory / "run.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f"Array test failed: {directory / 'run.log'}: {result.stdout}{result.stderr}")
    report = json.loads(result.stdout.strip().splitlines()[-1])
    if not report["passed"] or any(digest(ROOT / name) != value for name, value in before.items()):
        raise RuntimeError("Array test failed or its source changed during compilation")
    report.update(source_sha256=before, binary_sha256=digest(binary), compile_command=command,
                  run_command=[str(binary)], undefined_behavior_sanitizer=True)
    (directory / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/unified_validation/dip_array")
    parser.add_argument("--verilator", default="verilator")
    parser.add_argument("--sizes", nargs="+", type=int, default=[2, 3, 4, 8, 16])
    parser.add_argument("--jobs", type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    out = args.out.resolve()
    work = [(size, a, b) for size in args.sizes for a, b in ((8, 8), (16, 8), (16, 16))]
    reports = []
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(run_one, out, args.verilator, *item) for item in work]
        for future in as_completed(futures):
            report = future.result()
            reports.append(report)
            print(json.dumps({key: value for key, value in report.items()
                              if key not in ("source_sha256", "compile_command", "run_command")}), flush=True)
    result = dict(passed=all(report["passed"] for report in reports),
                  expected_configurations=len(work), completed_configurations=len(reports),
                  cases=sum(report["cases"] for report in reports),
                  checked_values=sum(report["checked_values"] for report in reports),
                  results=sorted(reports, key=lambda report: (report["size"], report["data_bits"], report["weight_bits"])))
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    main()
