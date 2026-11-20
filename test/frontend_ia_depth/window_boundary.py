#!/usr/bin/env python3
"""使用已编译 FPGA 模型检查非二次幂通道配置的数值与周期记录。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    previous = json.loads((model / "summary.json").read_text())
    if not proof["passed"] or not previous["passed"] or not previous["resident_stream_cycle_equivalent"]:
        raise RuntimeError("Formal and FPGA window comparison must be complete")
    summaries = {"current": previous, "reference": previous["reference"]}
    for name, summary in summaries.items():
        for path, value in summary["source_sha256"].items():
            if digest(Path(path)) != value:
                raise RuntimeError("Compiled model source differs")
        rtl = {"rtl/" + path.rsplit("/rtl/", 1)[1]: value
               for path, value in summary["source_sha256"].items() if "/rtl/" in path}
        expected = proof["source_sha256" if name == "current" else "reference_sha256"]
        if any(rtl[path] != value for path, value in expected.items()):
            raise RuntimeError("Formal and FPGA source differ")
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    main_text = runpy.run_path(str(ROOT / "test/frontend_decode_boundaries/numeric.py"))["MAIN"]
    cpp = out / "main.cpp"
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + main_text)
    results, traces = {}, {}
    for name, folder in (("reference", model / "reference"), ("current", model)):
        target = out / name
        target.mkdir(exist_ok=True)
        obj = folder / "obj"
        objects = [obj / filename for filename in
            ("verilated.o", "verilated_timing.o", "verilated_threads.o", "Vwindow_dma_top__ALL.a")]
        binary, trace = target / "boundary_windows", target / "cycles.csv"
        command = ["g++", "-std=c++20", "-O1", "-fcoroutines", "-DVERILATOR=1", "-DVM_TIMING=1",
                   "-fsanitize=undefined", "-fno-sanitize-recover=all", "-pthread", "-I" + str(obj),
                   "-I" + str(args.verilator_include), "-I" + str(args.verilator_include / "vltstd"),
                   str(cpp), *map(str, objects), "-latomic", "-o", str(binary)]
        for action, argv in (("compile", command), ("run", [str(binary), "+BOUNDARY_TRACE=" + str(trace)])):
            with (target / (action + ".log")).open("w") as stream:
                subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        text = (target / "run.log").read_text()
        if "DECODE_BOUNDARY_PASS" not in text:
            raise RuntimeError("Boundary numeric comparison is incomplete")
        traces[name] = trace.read_bytes()
        results[name] = dict(passed=True, tests=[line for line in text.splitlines()
            if line.startswith(("CASE ", "DECODE_BOUNDARY_PASS"))], trace_sha256=digest(trace),
            trace_cycles=len(traces[name].splitlines()), binary_sha256=digest(binary),
            model_objects_sha256={path.name: digest(path) for path in objects})
    if traces["current"] != traces["reference"] or results["current"]["tests"] != results["reference"]["tests"]:
        raise RuntimeError("Boundary data or cycle records differ")
    result = dict(passed=True, cycle_identical=True, source_sha256=proof["source_sha256"],
                  reference_sha256=proof["reference_sha256"], cases=results,
                  proof_sha256=digest(args.proof), model_summary_sha256=digest(model / "summary.json"),
                  main_sha256=digest(cpp))
    (out / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    print(results["current"]["tests"][-1], flush=True)


if __name__ == "__main__":
    main()
