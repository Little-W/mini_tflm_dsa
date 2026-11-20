#!/usr/bin/env python3
"""证明前端位置行尾与三个计数边界的并行等式比较。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/conv_im2col_frontend.sv")
HELPER = Path("rtl/common/add_equal.sv")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run_proof(out, name, top, source, temporal=False):
    sv, script, log_path = out / (name + ".sv"), out / (name + ".ys"), out / (name + ".log")
    sv.write_text(source)
    script.write_text(f"read_slang --top {top} " + shlex.quote(str(ROOT / HELPER)) + " " +
        shlex.quote(str(sv)) + f"\nprep -top {top} -flatten\n" +
        ("async2sync\nsat -verify -seq 2 -tempinduct -set-at 1 rst_n 0 -prove equivalent 1 -maxsteps 8\n"
         if temporal else "sat -verify -prove equivalent 1 -show-inputs -show-outputs\n"))
    with log_path.open("w") as log:
        subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"), "--worker", str(script)],
                       cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    expected = "Induction step proven: SUCCESS!" if temporal else "SAT proof finished - no model found: SUCCESS!"
    if expected not in log_path.read_text():
        raise RuntimeError("Proof incomplete: " + name)
    return dict(passed=True, source_sha256=digest(sv.read_bytes()), log_sha256=digest(log_path.read_bytes()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", default="f9235810")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", f"{args.reference}:{SOURCE}"], cwd=ROOT, text=True)
    pattern = r"      p_fast_wrap = c\.output_w != 16'd0 &&\n.*?;"
    current_expression = re.findall(pattern, current, re.S)
    reference_expression = re.findall(pattern, reference, re.S)
    if len(current_expression) != 1 or len(reference_expression) != 1:
        raise RuntimeError("Unexpected row boundary selection")
    comment = "      // 两个模加法等式并行完成，和值最高位直接选择相应的行尾关系。\n"
    normalized = current.replace(comment, "", 1).replace(current_expression[0], reference_expression[0], 1)
    decode_start = current.index("  // 三个解码范围的末项检查并行进行，控制结果不等待计数器加一。")
    decode_end = current.index("  assign p_delta =", decode_start)
    decode_body = current[decode_start:decode_end]
    decode_declarations = "  logic [2:0][31:0] decode_end_i_target;\n  logic [2:0] decode_end_o_equal;\n"
    normalized = normalized.replace(decode_body, "", 1).replace(decode_declarations, "", 1)
    reference_conditions = re.findall(r"if \((decode_inner\+1==32'\(c\.[a-z_]+\))\)", reference)
    if len(reference_conditions) != 3:
        raise RuntimeError("Unexpected sequential decode boundary conditions")
    for index, condition in enumerate(reference_conditions):
        replacement = f"if (decode_end_o_equal[{index}])"
        if normalized.count(replacement) != 1:
            raise RuntimeError("Decode comparison consumers changed")
        normalized = normalized.replace(replacement, "if (" + condition + ")", 1)
    if normalized != reference:
        raise RuntimeError("Changes outside decode boundary checks require verification")
    declarations = current[current.index("  logic [15:0] p_delta;"):current.index("  logic incoming_fast,")]
    arithmetic = current[current.index("  assign p_delta ="):current.index("  always_comb begin\n    p_fast_valid=")]
    if arithmetic not in reference or declarations not in reference:
        raise RuntimeError("Position arithmetic changed")
    comparison = """module position_wrap_proof(
    input logic [31:0] p_decode, last_p,
    input logic [15:0] last_x, output_width,
    output logic equivalent
);
  typedef struct packed {logic [15:0] output_w;} cfg_t;
  cfg_t c;
  logic [15:0] last_output_col_q;
  logic reference_wrap, current_wrap;
  assign c.output_w = output_width;
  assign last_output_col_q = output_width - 16'd1;
""" + declarations + arithmetic + "\n  always_comb begin\n" + \
        reference_expression[0].replace("p_fast_wrap", "reference_wrap") + "\n" + \
        current_expression[0].replace("p_fast_wrap", "current_wrap") + "\n  end\n" + \
        "  assign equivalent = reference_wrap == current_wrap;\nendmodule\n"
    arithmetic_result = run_proof(out, "arithmetic", "position_wrap_proof", comparison)
    updates = re.findall(r"\blast_output_col_q\s*<=\s*([^;]+);", current)
    if updates != ["0", "cfg.output_w-16'd1"]:
        raise RuntimeError("Output column state assignments require verification")
    first = current.index("last_output_col_q<=0;")
    block_start = current.rfind("  always_ff @(posedge clk or negedge rst_n) begin", 0, first)
    block_end = current.index("\n  end\n", first)
    block = current[block_start:block_end]
    if len(re.findall(r"\blast_output_col_q\s*<=", block)) != 2:
        raise RuntimeError("Output column updates span additional state blocks")
    if "if (!rst_n) begin" not in block or "end else if (cfg_valid && cfg_ready) begin" not in block:
        raise RuntimeError("Output column state uses a different update condition")
    verify_config_state = runpy.run_path(str(ROOT / "test/frontend_shape_register/run.py"))["verify_config_state"]
    c_updates = verify_config_state(current)
    state = f"""module output_column_state_proof(
    input logic clk, rst_n, cfg_valid, cfg_ready,
    input logic [15:0] cfg_output_w,
    output logic equivalent
);
  typedef struct packed {{logic [15:0] output_w;}} cfg_t;
  cfg_t c, cfg;
  logic [15:0] last_output_col_q;
  assign cfg.output_w = cfg_output_w;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c <= {c_updates[0]};
      last_output_col_q <= {updates[0]};
    end else if (cfg_valid && cfg_ready) begin
      c <= {c_updates[1]};
      last_output_col_q <= {updates[1]};
    end
  end
  assign equivalent = c.output_w == 16'd0 || last_output_col_q == c.output_w - 16'd1;
endmodule
"""
    state_result = run_proof(out, "configuration_state", "output_column_state_proof", state, temporal=True)
    zero = comparison.replace("assign last_output_col_q = output_width - 16'd1;",
        "assign last_output_col_q = output_width;").replace("assign c.output_w = output_width;",
        "assign c.output_w = 16'd0;")
    zero_result = run_proof(out, "zero_width", "position_wrap_proof", zero)
    decode = """module decode_boundary_proof(
    input logic [31:0] decode_inner,
    input logic [15:0] output_width, group_channels, kernel_width,
    output logic equivalent
);
  typedef struct packed {logic [15:0] output_w, group_c, kernel_w;} cfg_t;
  cfg_t c;
  logic [2:0] reference_equal;
  assign c.output_w = output_width;
  assign c.group_c = group_channels;
  assign c.kernel_w = kernel_width;
""" + decode_declarations + decode_body + "\n" + \
        "\n".join(f"  assign reference_equal[{index}] = {condition};"
                  for index, condition in enumerate(reference_conditions)) + \
        "\n  assign equivalent = decode_end_o_equal == reference_equal;\nendmodule\n"
    decode_result = run_proof(out, "decode_boundaries", "decode_boundary_proof", decode)
    report = dict(passed=True, reference_ref=args.reference,
        reference_commit=subprocess.check_output(["git", "rev-parse", args.reference], cwd=ROOT, text=True).strip(),
        source_sha256=digest(current.encode()), reference_sha256=digest(reference.encode()),
        unchanged_outside_decode_boundaries=True, actual_source_arithmetic=True,
        arithmetic_input_bits=96, arithmetic_inputs_constrained=False,
        arithmetic=arithmetic_result, configuration_state=state_result,
        configuration_register_bits=32, initial_reset=True, later_inputs_constrained=False,
        zero_width_any_last_column=zero_result, decode_boundaries=decode_result,
        decode_boundary_input_bits=80, decode_boundary_result_bits=3,
        helper_sha256=digest((ROOT / HELPER).read_bytes()))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
