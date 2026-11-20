#!/usr/bin/env python3
"""核对实际 FPGA 窗口模型的数值与逐周期结果，支持复用已验证的参考模型。"""
import argparse
import gzip
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


def trace_content(path):
    return path.read_bytes() if path.exists() else gzip.decompress(path.with_suffix(path.suffix + ".gz").read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--reference-model", type=Path, required=True)
    parser.add_argument("--reference-boundary", type=Path, help="已完成参考几何测试的 summary.json")
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--verilator-include", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    models = {"reference": args.reference_model.resolve(), "current": args.model.resolve()}
    proof = json.loads(args.proof.read_text())
    if not proof["passed"] or not proof["unchanged_outside_conditional_increment"]:
        raise RuntimeError("Retirement arithmetic proof must pass")
    summaries = {name: json.loads((path / "summary.json").read_text()) for name, path in models.items()}
    for name, summary in summaries.items():
        if not summary["passed"] or not summary["fpga"]:
            raise RuntimeError("Actual FPGA window test must pass: " + name)
        for path, expected in summary["source_sha256"].items():
            if digest(Path(path)) != expected:
                raise RuntimeError("Compiled source changed: " + path)
    current, reference = summaries["current"], summaries["reference"]
    current_rtl, reference_rtl = rtl_sources(current), rtl_sources(reference)
    if current_rtl[SOURCE] != proof["source_sha256"] or reference_rtl[SOURCE] != proof["reference_sha256"]:
        raise RuntimeError("Formal and numeric sources differ")
    if set(current_rtl) != set(reference_rtl) or {
            name for name, value in current_rtl.items() if reference_rtl[name] != value} != {SOURCE}:
        raise RuntimeError("Additional RTL differences require verification")
    if sorted(value for name, value in current["source_sha256"].items() if "/rtl/" not in name) != \
            sorted(value for name, value in reference["source_sha256"].items() if "/rtl/" not in name):
        raise RuntimeError("Simulation harnesses differ")
    resident = {name: trace_content(path / "resident_stream.csv") for name, path in models.items()}
    if resident["current"] != resident["reference"] or current["tests"] != reference["tests"]:
        raise RuntimeError("Resident window cycle records or numeric results differ")
    for name, summary in summaries.items():
        if hashlib.sha256(resident[name]).hexdigest() != summary["resident_stream_sha256"]:
            raise RuntimeError("Resident trace differs from its model result")
    boundary_main = runpy.run_path(str(ROOT / "test/frontend_decode_boundaries/numeric.py"))["MAIN"]
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    cpp = out / "boundary_main.cpp"
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + boundary_main)
    cases, traces = {}, {}
    for name, model in models.items():
        obj = model / "obj"
        dependencies = [obj / filename for filename in
            ("verilated.o", "verilated_timing.o", "verilated_threads.o", "Vwindow_dma_top__ALL.a")]
        object_hashes = {path.name: digest(path) for path in dependencies}
        if name == "reference" and args.reference_boundary:
            previous = json.loads(args.reference_boundary.read_text())
            result = previous["boundary"]["reference"]
            if not previous["passed"] or previous["reference_commit"] != proof["reference_commit"] or \
                    previous["reference_model_sha256"] != digest(model / "summary.json") or \
                    previous["boundary_main_sha256"] != digest(cpp) or result["model_objects_sha256"] != object_hashes:
                raise RuntimeError("Reference boundary model or executable sources differ")
            traces[name] = trace_content(args.reference_boundary.parent / "reference/cycles.csv")
            if hashlib.sha256(traces[name]).hexdigest() != result["trace_sha256"]:
                raise RuntimeError("Stored reference boundary trace differs")
            cases[name] = dict(result, reused_summary_sha256=digest(args.reference_boundary))
            continue
        folder = out / name
        folder.mkdir(exist_ok=True)
        binary, trace = folder / "boundary_windows", folder / "cycles.csv"
        command = ["g++", "-std=c++20", "-O1", "-fcoroutines", "-DVERILATOR=1", "-DVM_TIMING=1",
            "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I" + str(obj),
            "-I" + str(args.verilator_include), "-I" + str(args.verilator_include / "vltstd"),
            str(cpp), *map(str, dependencies), "-latomic", "-o", str(binary)]
        run(command, folder / "compile.log")
        run([binary, "+BOUNDARY_TRACE=" + str(trace)], folder / "run.log")
        text = (folder / "run.log").read_text()
        if "DECODE_BOUNDARY_PASS" not in text:
            raise RuntimeError("Boundary numeric test incomplete")
        traces[name] = trace.read_bytes()
        cases[name] = dict(passed=True, binary_sha256=digest(binary), trace_sha256=digest(trace),
            trace_cycles=len(traces[name].splitlines()), log_sha256=digest(folder / "run.log"),
            model_objects_sha256=object_hashes,
            tests=[line for line in text.splitlines() if line.startswith(("CASE ", "DECODE_BOUNDARY_PASS"))])
    if traces["reference"] != traces["current"] or cases["reference"]["tests"] != cases["current"]["tests"]:
        raise RuntimeError("Boundary window cycle records or numeric results differ")
    report = dict(passed=True, cycle_identical=True, source_sha256=proof["source_sha256"],
        reference_sha256=proof["reference_sha256"], reference_commit=proof["reference_commit"],
        proof_summary_sha256=digest(args.proof),
        model_summary_sha256={name: digest(path / "summary.json") for name, path in models.items()},
        resident_trace_cycles=current["resident_stream_cycles"],
        resident_trace_sha256=current["resident_stream_sha256"], window_tests=current["tests"],
        boundary_main_sha256=digest(cpp), boundary=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "cycle_identical", "resident_trace_cycles")}), flush=True)
    print(cases["current"]["tests"][-1], flush=True)


if __name__ == "__main__":
    main()
