#!/usr/bin/env python3
"""对全部坐标及乘积输入证明预测器的并行借位减法。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/dma/cache/conv_next_use_predictor.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="2bd1d2b3")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    declarations = ("  logic [1:0][32:0] coordinate_pad;\n"
                    "  logic [1:0][31:0] coordinate_product;\n"
                    "  logic [1:0][33:0] coordinate_difference;\n")
    start = current.index("  // 高十八位的两种借位结果并行计算，低十六位只选择相应结果。")
    end = current.index("  always_comb begin", start)
    arithmetic = current[start:end]
    original_start = reference.index("    // 输入坐标与填充之和在启动时保存，候选阶段使用34位有符号减法。")
    original_end = reference.index("    oy_s0 =", original_start)
    original = reference[original_start:original_end]
    normalized = current.replace(declarations, "", 1).replace(arithmetic, "", 1)
    normalized = normalized.replace("    oy_s0 =", original + "    oy_s0 =", 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside coordinate subtraction require verification")
    proof = out / "coordinate_difference.sv"
    proof.write_text("""module coordinate_difference_proof(
    input logic [32:0] y_pad_q, x_pad_q,
    input logic [31:0] mul_y_s0, mul_x_s0,
    output logic equivalent
);
  logic signed [33:0] ny_s0, nx_s0, reference_y, reference_x;
""" + declarations + arithmetic + "\n  always_comb begin\n" +
        original.replace("ny_s0", "reference_y").replace("nx_s0", "reference_x") +
        "  end\n  assign equivalent={ny_s0,nx_s0}=={reference_y,reference_x};\nendmodule\n")
    script, log_path = out / "run.ys", out / "formal.log"
    script.write_text("read_slang --top coordinate_difference_proof " + shlex.quote(str(proof)) +
        "\nprep -top coordinate_difference_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
        raise RuntimeError("Coordinate subtraction comparison incomplete")
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_coordinate_subtraction=True, actual_source_expressions=True,
        input_bits=130, result_bits=68, inputs_constrained=False,
        proof_sha256=digest(proof.read_bytes()), script_sha256=digest(script.read_bytes()),
        log_sha256=digest(log_path.read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
