#!/usr/bin/env python3
"""读取前端实际源码，证明固定商余数表及所有通道消费者。"""
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
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tokens(text):
    return re.sub(r"\s+", "", re.sub(r"//[^\n]*", "", text))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="fa66f107")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True)
    start = current.index("  // 五位位置同时查出除三的商和余数，组内通道直接保留高位位置。")
    end = current.index("  always_comb begin", start)
    table = current[start:end]
    original = re.search(r"    current_q_times11=.*?;\s*current_q_div3=.*?;", reference, re.S)[0]
    replacements = {
        "  assign group_range_channel[3] = current_q_remainder;":
            "  assign group_range_channel[3] = 16'(q0 - 3 * 32'(current_q_div3));",
        "            ch_q <= current_q_remainder;": "            ch_q <= 16'(q0-3*32'(current_q_div3));",
        "            ch0_q <= current_q_remainder;": "            ch0_q <= 16'(q0-3*32'(current_q_div3));",
    }
    normalized = current[:start] + current[end:].replace("  always_comb begin\n", "  always_comb begin\n" + original + "\n", 1)
    normalized = normalized.replace("  logic [15:0] current_q_remainder;\n", "", 1)
    normalized = normalized.replace("  logic [4:0] current_q_div3;", "  logic [9:0] current_q_times11;\n  logic [4:0] current_q_div3;", 1)
    for replacement, old in replacements.items():
        if current.count(replacement) != 1 or reference.count(old) != 1:
            raise RuntimeError("Channel consumer source changed")
        normalized = normalized.replace(replacement, old, 1)
    if tokens(normalized) != tokens(reference):
        raise RuntimeError("Changes outside the quotient/remainder expressions require verification")
    expected = original.replace("current_q_times11", "reference_times11").replace("current_q_div3", "reference_div3")
    reference_consumers = []
    current_consumers = []
    for index, (new, old) in enumerate(replacements.items()):
        reference_expression = old.split("<=", 1)[1] if "<=" in old else old.split("=", 1)[1]
        current_expression = new.split("<=", 1)[1] if "<=" in new else new.split("=", 1)[1]
        reference_consumers.append(f"  assign reference_channel[{index}] = " + reference_expression.replace("current_q_div3", "reference_div3"))
        current_consumers.append(f"  assign current_channel[{index}] = " + current_expression)
    proof = out / "quotient_remainder.sv"
    proof.write_text("""module quotient_remainder_proof(
  input logic [31:0] q0,
  output logic equivalent
);
  logic [4:0] current_q_div3, reference_div3;
  logic [15:0] current_q_remainder;
  logic [9:0] reference_times11;
  logic [2:0][15:0] reference_channel, current_channel;
""" + table + "\n  always_comb begin\n" + expected + "\n  end\n" +
        "\n".join(reference_consumers + current_consumers) +
        "\n  assign equivalent={current_q_div3,current_channel}=={reference_div3,reference_channel};\nendmodule\n")
    import pyosys
    library = Path(pyosys.__file__).parent / "share/xilinx/cells_sim.v"
    model = re.search(r"^module LUT6_2\b.*?^endmodule", library.read_text(), re.M | re.S)[0]
    primitive_file = out / "xilinx_primitives.sv"
    primitive_file.write_text(re.sub(r"\bspecify\b.*?\bendspecify\b", "", model, flags=re.S) + "\n")
    cases = []
    for fpga in (False, True):
        name = "fpga" if fpga else "generic"
        script, log_path = out / (name + ".ys"), out / (name + ".log")
        sources = [proof] + ([primitive_file] if fpga else [])
        defines = "-D XILINX_FPGA -D SYNTHESIS -D YOSYS -D VERIFIC " if fpga else ""
        script.write_text("read_slang --top quotient_remainder_proof " + defines +
            " ".join(shlex.quote(str(p)) for p in sources) +
            "\nprep -top quotient_remainder_proof -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n")
        with log_path.open("w") as log:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        if "SAT proof finished - no model found: SUCCESS!" not in log_path.read_text():
            raise RuntimeError("Quotient/remainder comparison incomplete: " + name)
        cases.append(dict(mode=name, passed=True, script_sha256=digest(script.read_bytes()), log_sha256=digest(log_path.read_bytes())))
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_quotient_remainder=True, actual_source_expressions=True,
        input_bits=32, result_bits=53, inputs_constrained=False, consumers_checked=3,
        primitive_library_sha256=digest(library.read_bytes()), primitive_model_sha256=digest(primitive_file.read_bytes()),
        proof_sha256=digest(proof.read_bytes()), cases=cases)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
