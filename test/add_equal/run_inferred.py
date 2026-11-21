#!/usr/bin/env python3
"""验证模加等式的资源推断与逐位进位实现。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 2, 16, 23, 24, 28, 32, 33, 47, 48, 64)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--source", default=ROOT / "rtl/common/add_equal.sv", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshot = out / "add_equal.sv"
    snapshot.write_bytes(args.source.read_bytes())
    helper = ROOT / "test/add_equal/run_formal.py"
    spec = importlib.util.spec_from_file_location("add_equal_native_reference", helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    miter_text = module.MITER.replace("p_width = 32", "p_width = 32, parameter bit p_infer_dsp = 1'b1")
    miter_text = miter_text.replace(".p_width(p_width)", ".p_width(p_width), .p_infer_dsp(p_infer_dsp)")
    miter = out / "miter.sv"
    miter.write_text(miter_text)
    report = {"passed": False, "source_sha256": digest(args.source),
              "test_source_sha256": digest(Path(__file__)),
              "native_reference_helper_sha256": digest(helper),
              "inputs_constrained": False, "formal": [], "four_state": []}
    for width in WIDTHS:
        for infer in (0, 1):
            script = out / f"width{width}_infer{infer}.ys"
            script.write_text(
                "read_slang -D SYNTHESIS=1 -D XILINX_FPGA=1 --top add_equal_proof " +
                f"-Gp_width={width} -Gp_infer_dsp={infer} " +
                shlex.join([str(snapshot), str(miter)]) + "\n" +
                "prep -top add_equal_proof -flatten\ncheck -assert\n" +
                "sat -verify -prove o_equivalent 1 -show-inputs -show-outputs\n")
            log = script.with_suffix(".log")
            text = execute([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], log)
            if "SAT proof finished - no model found: SUCCESS!" not in text:
                raise RuntimeError("模加等式证明未完成")
            row = {"passed": True, "width": width, "infer_dsp": bool(infer),
                   "synthesis_expression": True, "unconstrained_input_bits": 3 * width + 1,
                   "preserve_modes": ["default", 0, 1], "log_sha256": digest(log)}
            report["formal"].append(row)
            print(json.dumps(row), flush=True)
    bench = ROOT / "test/add_equal/tb_four_state.sv"
    report["four_state_bench_sha256"] = digest(bench)
    for width in WIDTHS:
        for mode, defines in (("fpga", ["-DXILINX_FPGA=1"]), ("generic", ["-DASIC_SYNTHESIS=1"])):
            name = f"four_state_width{width}_{mode}"
            binary = out / (name + ".vvp")
            execute(["iverilog", "-g2012", *defines, "-s", "tb_add_equal_four_state",
                     f"-Ptb_add_equal_four_state.p_width={width}", "-o", str(binary),
                     str(snapshot), str(bench)], out / (name + "_build.log"))
            log = out / (name + ".log")
            text = execute(["vvp", str(binary)], log)
            if "ADD_EQUAL_FOUR_STATE_PASS" not in text:
                raise RuntimeError("模加等式四态检查未完成")
            report["four_state"].append({"passed": True, "width": width, "configuration": mode,
                "tests": 4 ** (3 * width + 1) if width <= 2 else 6000,
                "preserve_modes": ["default", 0, 1], "log_sha256": digest(log)})
    if digest(args.source) != report["source_sha256"]:
        raise RuntimeError("验证期间源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": True, "formal_profiles": len(report["formal"]),
                      "four_state_profiles": len(report["four_state"])}), flush=True)


if __name__ == "__main__":
    main()
