#!/usr/bin/env python3
"""复用固定参考与当前 FPGA 模型，逐周期比较非幂次配置的完整窗口结果。"""
import argparse
import filecmp
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "rtl/npu/conv/conv_im2col_frontend.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open("w") as stream:
        stream.write("$ " + shlex.join(map(str, command)) + "\n")
        stream.flush()
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


def rtl_sources(summary):
    return {"rtl/" + name.rsplit("/rtl/", 1)[1]: value
            for name, value in summary["source_sha256"].items() if "/rtl/" in name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--verilator-include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out, model = args.out.resolve(), args.model.resolve()
    out.mkdir(parents=True, exist_ok=True)
    proof = json.loads(args.proof.read_text())
    current = json.loads((model / "summary.json").read_text())
    reference = json.loads((model / "reference/summary.json").read_text())
    if not proof["passed"] or not current["passed"] or not reference["passed"] or not current["fpga"] or not reference["fpga"]:
        raise RuntimeError("Formal and complete FPGA comparisons must pass")
    current_rtl, reference_rtl = rtl_sources(current), rtl_sources(reference)
    if current_rtl[SOURCE] != proof["source_sha256"] or reference_rtl[SOURCE] != proof["reference_sha256"]:
        raise RuntimeError("Formal and numeric sources differ")
    differences = {name for name, value in current_rtl.items() if reference_rtl.get(name) != value}
    covered = {SOURCE}
    if "helper_sha256" in proof:
        helper = "rtl/common/add_equal.sv"
        if current_rtl[helper] != proof["helper_sha256"] or reference_rtl[helper] != proof["helper_sha256"]:
            raise RuntimeError("Helper proof and numeric sources differ")
        if not proof.get("helper_unchanged", False):
            covered.add(helper)
    if differences != covered:
        raise RuntimeError("Additional RTL changes require verification")
    for summary in (current, reference):
        for path, expected in summary["source_sha256"].items():
            if digest(Path(path)) != expected:
                raise RuntimeError("Compiled source changed: " + path)
    if not current["resident_stream_cycle_equivalent"]:
        raise RuntimeError("Resident window comparison must pass")
    boundary_main = runpy.run_path(str(ROOT / "test/frontend_decode_boundaries/numeric.py"))["MAIN"]
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    cpp = out / "boundary_main.cpp"
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + boundary_main)
    cases = {}
    for label, folder in (("reference", model / "reference"), ("current", model)):
        destination = out / label
        destination.mkdir(exist_ok=True)
        obj = folder / "obj"
        dependencies = [obj / name for name in
            ("verilated.o", "verilated_timing.o", "verilated_threads.o", "Vwindow_dma_top__ALL.a")]
        binary, trace = destination / "boundary_windows", destination / "cycles.csv"
        command = ["g++", "-std=c++20", "-O1", "-fcoroutines", "-DVERILATOR=1", "-DVM_TIMING=1",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I" + str(obj),
            "-I" + str(args.verilator_include), "-I" + str(args.verilator_include / "vltstd"),
            str(cpp), *map(str, dependencies), "-latomic", "-o", str(binary)]
        run(command, destination / "compile.log")
        run([binary, "+BOUNDARY_TRACE=" + str(trace)], destination / "run.log")
        text = (destination / "run.log").read_text()
        if "DECODE_BOUNDARY_PASS" not in text:
            raise RuntimeError("Boundary numeric test incomplete")
        cases[label] = dict(passed=True, binary_sha256=digest(binary), trace_sha256=digest(trace),
            trace_cycles=sum(1 for _ in trace.open()), log_sha256=digest(destination / "run.log"),
            model_objects_sha256={path.name: digest(path) for path in dependencies},
            tests=[line for line in text.splitlines() if line.startswith(("CASE ", "DECODE_BOUNDARY_PASS"))])
    if not filecmp.cmp(out / "reference/cycles.csv", out / "current/cycles.csv", shallow=False):
        raise RuntimeError("Boundary window cycle records differ")
    if cases["reference"]["tests"] != cases["current"]["tests"]:
        raise RuntimeError("Boundary window statistics differ")
    report = dict(passed=True, cycle_identical=True, source_sha256=proof["source_sha256"],
        reference_sha256=proof["reference_sha256"], reference_commit=proof["reference_commit"],
        proof_summary_sha256=digest(args.proof), current_model_sha256=digest(model / "summary.json"),
        reference_model_sha256=digest(model / "reference/summary.json"),
        resident_trace_cycles=current["resident_stream_cycles"],
        resident_trace_sha256=current["resident_stream_sha256"],
        boundary_main_sha256=digest(cpp), boundary=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "cycle_identical", "resident_trace_cycles")}), flush=True)
    print(cases["current"]["tests"][-1], flush=True)


if __name__ == "__main__":
    main()
