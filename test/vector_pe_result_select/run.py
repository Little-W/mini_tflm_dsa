#!/usr/bin/env python3
"""验证 PE 结果资格寄存、全部运算和四态使能保持。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/npu/conv/vector_pe.sv")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def combinational(text: str, name: str) -> str:
    capture = re.search(r"  always_ff @\(posedge clk\) begin\n    if \(i_en\) begin\n"
                        r"(.*?)\n    end\n  end\n", text, re.S)
    if capture is None:
        raise ValueError("需要完整的共同使能寄存过程")
    result = text.replace("module vector_pe #", f"module {name} #", 1)
    result = result.replace("  input wire logic clk,\n", "")
    result = result.replace("  input wire logic i_en,\n", "")
    return result.replace(capture[0], "  always_comb begin\n" +
                          capture[1].replace("<=", "=") + "\n  end\n")


def run(command: list[str], log: Path, timeout: int = 240) -> None:
    with log.open("w") as stream:
        stream.write("$ " + shlex.join(map(str, command)) + "\n")
        stream.flush()
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="f821b566")
    parser.add_argument("--trials", type=int, default=2048)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = ROOT / SOURCE
    revision = subprocess.check_output(["git", "rev-parse", args.reference + "^{commit}"],
                                       cwd=ROOT, text=True).strip()
    original = subprocess.check_output(["git", "show", f"{revision}:{SOURCE}"],
                                       cwd=ROOT, text=True)
    hashes = {str(current): digest(current), str(Path(__file__)): digest(Path(__file__))}
    reference = out / "reference.sv"
    reference.write_text(original.replace("module vector_pe #", "module reference_pe #", 1))
    arithmetic = out / "arithmetic.sv"
    arithmetic.write_text(combinational(original, "reference_arithmetic") + "\n" +
                          combinational(current.read_text(), "candidate_arithmetic") + r'''
module arithmetic_proof #(
  parameter bit EXTENDED=1'b0, SELECTED=1'b0
)(
  input logic [2:0] i_op,
  input logic signed [15:0] i_a, i_b,
  input logic signed [31:0] i_acc,
  output logic equal
);
  wire signed [31:0] actual_result, reference_result;
  candidate_arithmetic #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_actual (
    .i_op,.i_a,.i_b,.i_acc,.o_result(actual_result));
  reference_arithmetic #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_reference (
    .i_op,.i_a,.i_b,.i_acc,.o_result(reference_result));
  assign equal=actual_result==reference_result;
endmodule
''')
    state = out / "state.sv"
    state.write_text(r'''
module state_proof #(
  parameter bit EXTENDED=1'b0, SELECTED=1'b0
)(
  input logic clk, i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] i_a, i_b,
  input logic signed [31:0] i_acc,
  output logic equal
);
  logic [2:0] saved_op;
  logic signed [15:0] saved_a, saved_b;
  logic signed [31:0] saved_acc, selected_acc;
  logic multiply, zero, compare;
  always_ff @(posedge clk) if (i_en) begin
    saved_op<=i_op; saved_a<=i_a; saved_b<=i_b; saved_acc<=i_acc;
  end
  always_comb begin
    selected_acc=saved_acc;
    if (!SELECTED) case (saved_op)
      3'd4, 3'd5, 3'd6: selected_acc=32'sd0;
      default: begin end
    endcase
    multiply=1'b0; zero=1'b0; compare=1'b0;
    case (saved_op)
      3'd0, 3'd1, 3'd4: multiply=1'b1;
      3'd2, 3'd3: compare=1'b1;
      3'd5, 3'd6: zero=1'b1;
      default: begin end
    endcase
  end
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_actual (
    .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result());
  assign equal={u_actual.op,u_actual.a,u_actual.b,u_actual.acc,
      u_actual.result_multiply,u_actual.result_zero,u_actual.result_compare} ==
      {saved_op,saved_a,(saved_op==3'd1 ? 16'sd1 : saved_b),selected_acc,multiply,zero,compare};
endmodule
''')
    rows = []
    for extended in (0, 1):
        for selected in (0, 1):
            profile = f"extended{extended}_selected{selected}"
            checks = []
            for name, sources, command in (
                ("arithmetic", [arithmetic], "sat -verify -prove equal 1"),
                ("state", [current, state],
                 "sat -verify -seq 2 -tempinduct -initsteps 2 -maxsteps 6 "
                 "-set-at 1 i_en 1 -prove equal 1"),
            ):
                script = out / f"{profile}_{name}.ys"
                log = script.with_suffix(".log")
                script.write_text(f"read_slang --top {name}_proof -GEXTENDED={extended} "
                                  f"-GSELECTED={selected} " + shlex.join(map(str, sources)) +
                                  f"\nprep -top {name}_proof -flatten\nopt -full\n{command}\n")
                run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
                if name == "state" and "Induction step proven: SUCCESS" not in log.read_text():
                    raise RuntimeError("寄存器关系的时序归纳未完成")
                checks.append(dict(name=name, passed=True, log_sha256=digest(log)))
            rows.append(dict(profile=profile, extended=extended, accumulator_preselected=selected,
                             operation_codes=8, arithmetic_output_bits=32, registered_state_bits=70,
                             arbitrary_future_enables=True, checks=checks))
            print("PE_RESULT_FORMAL_PASS", profile, flush=True)
    bench = out / "four_state.sv"
    bench.write_text((Path(__file__).parent / "four_state.sv").read_text())
    binary = out / "four_state.vvp"
    run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.p_trials={args.trials}",
         "-o", binary, current, reference, bench], out / "four_state_compile.log")
    run(["vvp", binary], out / "four_state.log")
    match = re.search(r"PE_RESULT_FOUR_STATE_PASS samples=(\d+) checks=(\d+) hold_checks=(\d+)",
                      (out / "four_state.log").read_text())
    if not match:
        raise RuntimeError("四态检查未完成")
    if hashes != {name: digest(Path(name)) for name in hashes}:
        raise RuntimeError("检查期间输入源码发生变化")
    report = dict(passed=True, reference_commit=revision, source_sha256=hashes,
                  reference_sha256=digest(reference), profiles=rows,
                  initialization="State relation starts after the first enabled capture; later inputs and enables are unconstrained",
                  four_state=dict(samples=int(match[1]), compared_outputs=int(match[2]),
                                  hold_checks=int(match[3]), test_sha256=digest(bench)))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(match[0], flush=True)


if __name__ == "__main__":
    main()
