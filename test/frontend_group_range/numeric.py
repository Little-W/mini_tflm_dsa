#!/usr/bin/env python3
"""固定参考源码并逐周期比较实际 FPGA 窗口与逐步译码结果。"""
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
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            result.update(block)
    return result.hexdigest()


def run(command, log):
    with log.open("w") as stream:
        stream.write("$ " + shlex.join(map(str, command)) + "\n")
        stream.flush()
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)


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
    if not proof["passed"] or not proof["unchanged_outside_range_state"] or not current["passed"] or not current["fpga"]:
        raise RuntimeError("The formal comparison and complete FPGA numeric test must pass")
    hashes = current["source_sha256"]
    if hashes[str(ROOT / SOURCE)] != proof["source_sha256"]:
        raise RuntimeError("Formal and numeric candidate sources differ")
    for path, expected in hashes.items():
        if digest(Path(path)) != expected:
            raise RuntimeError("Current model input changed: " + path)
    reference = out / "reference"
    reference.mkdir(exist_ok=True)
    source_map = {}
    reference_hashes = {}
    rtl_differences = []
    for name, expected in hashes.items():
        source = Path(name)
        relative = source.relative_to(ROOT)
        if relative.parts[0] == "rtl":
            target = reference / "sources" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = subprocess.check_output(["git", "show", f"{proof['reference_commit']}:{relative}"], cwd=ROOT)
            target.write_bytes(data)
            source_map[name] = str(target)
            reference_hashes[str(target)] = digest(target)
            if digest(target) != expected:
                rtl_differences.append(str(relative))
        else:
            source_map[name] = name
            reference_hashes[name] = expected
    if rtl_differences != [SOURCE]:
        raise RuntimeError("Additional RTL model differences require verification")
    if reference_hashes[str(reference / "sources" / SOURCE)] != proof["reference_sha256"]:
        raise RuntimeError("Formal and numeric reference sources differ")
    verilator = shlex.split((model / "elaborate.log").read_text().splitlines()[0])[1]
    command = [verilator, "--cc", "--exe", "--timing", "--assert", "--top-module", "window_dma_top",
        "-Wno-fatal", "-Wno-PINMISSING", "--Mdir", str(reference / "obj"),
        "--output-groups", "0", "--output-split", "12000", "-CFLAGS",
        "-std=c++20 -DWINDOW_RESPONSE_INTERVAL=3 -fsanitize=undefined -fno-sanitize-recover=all",
        "-LDFLAGS", "-fsanitize=undefined", "-DSYNTHESIS=1", "-DXILINX_FPGA=1", "-DNPU_SIM_ASSERT=1",
        str(ROOT / "test/conv_npu/simulator.vlt"), *source_map.values()]
    run(command, reference / "elaborate.log")
    make = ["make", "-C", str(reference / "obj"), "-f", "Vwindow_dma_top.mk", "-j", "1",
        "OPT_FAST=-O1", "OPT_SLOW=-O0", "OPT_GLOBAL=-O1", "VK_PCH_I_FAST=", "VK_PCH_I_SLOW=", "CFG_CXXFLAGS_PCH=-E"]
    run(make, reference / "compile.log")
    trace = reference / "resident_stream.csv"
    binary = reference / "obj/Vwindow_dma_top"
    run([binary, "+WINDOW_TRACE=" + str(trace)], reference / "run.log")
    text = (reference / "run.log").read_text()
    if "WINDOW_DMA_PASS" not in text:
        raise RuntimeError("Reference window test incomplete")
    if not filecmp.cmp(trace, model / "resident_stream.csv", shallow=False):
        raise RuntimeError("Resident window cycle records differ")
    reference_summary = dict(passed=True, fpga=True, source_sha256=reference_hashes,
        reference_commit=proof["reference_commit"], executable_sha256=digest(binary),
        resident_stream_sha256=digest(trace),
        resident_stream_cycles=sum(1 for _ in trace.open()),
        tests=[line for line in text.splitlines() if line.startswith(("CASE ", "WINDOW_DMA_PASS"))])
    if reference_summary["tests"] != current["tests"]:
        raise RuntimeError("Reference window statistics differ")
    (reference / "summary.json").write_text(json.dumps(reference_summary, indent=2) + "\n")

    boundary_main = runpy.run_path(str(ROOT / "test/frontend_decode_boundaries/numeric.py"))["MAIN"]
    original = (ROOT / "test/window_dma/main.cpp").read_text()
    cpp = out / "boundary_main.cpp"
    cpp.write_text(original[:original.index("int main(int argc,char** argv)")] + boundary_main)
    boundary = {}
    for label, folder in (("reference", reference), ("current", model)):
        destination = out / ("boundary_" + label)
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
        boundary[label] = dict(passed=True, binary_sha256=digest(binary), trace_sha256=digest(trace),
            trace_cycles=sum(1 for _ in trace.open()), log_sha256=digest(destination / "run.log"),
            model_objects_sha256={path.name: digest(path) for path in dependencies},
            tests=[line for line in text.splitlines() if line.startswith(("CASE ", "DECODE_BOUNDARY_PASS"))])
    if not filecmp.cmp(out / "boundary_reference/cycles.csv", out / "boundary_current/cycles.csv", shallow=False):
        raise RuntimeError("Boundary window cycle records differ")
    if boundary["reference"]["tests"] != boundary["current"]["tests"]:
        raise RuntimeError("Boundary window statistics differ")
    report = dict(passed=True, cycle_identical=True, source_sha256=proof["source_sha256"],
        reference_sha256=proof["reference_sha256"], reference_commit=proof["reference_commit"],
        proof_summary_sha256=digest(args.proof), current_model_sha256=digest(model / "summary.json"),
        reference_model_sha256=digest(reference / "summary.json"),
        resident_trace_cycles=current["resident_stream_cycles"],
        resident_trace_sha256=current["resident_stream_sha256"],
        boundary_main_sha256=digest(cpp), boundary=boundary)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: report[key] for key in ("passed", "cycle_identical", "resident_trace_cycles")}), flush=True)
    print(boundary["current"]["tests"][-1], flush=True)


if __name__ == "__main__":
    main()
