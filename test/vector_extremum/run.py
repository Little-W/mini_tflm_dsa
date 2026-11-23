#!/usr/bin/env python3
"""验证统一寄存 PE 的全部操作、累加预选、使能保持和四态输入。"""
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
sys.path.insert(0, str(ROOT / "test"))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clocked_reference(text):
    """在使能边沿保存参考运算的完整公开输入。"""
    arithmetic = re.search(r"module vector_pe\b.*?endmodule", text, re.S)
    if arithmetic is None:
        raise ValueError("参考源码缺少 vector_pe")
    arithmetic = arithmetic[0].replace("module vector_pe", "module reference_comb_pe", 1)
    arithmetic = re.sub(r"\(\*.*?\*\)", "", arithmetic, flags=re.S)
    return arithmetic + r'''
module vector_pe #(
  parameter bit ENABLE_EXTENDED_MULTIPLY=1'b1,
  parameter bit p_accumulator_preselected=1'b0
) (
  input logic clk, i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] i_a, i_b,
  input logic signed [31:0] i_acc,
  output wire signed [31:0] o_result
);
  logic [2:0] r_op;
  logic signed [15:0] r_a, r_b;
  logic signed [31:0] r_acc;
  always_ff @(posedge clk) if (i_en) begin
    r_op<=i_op; r_a<=i_a; r_b<=i_b; r_acc<=i_acc;
  end
  reference_comb_pe #(
    .ENABLE_EXTENDED_MULTIPLY(ENABLE_EXTENDED_MULTIPLY),
    .p_accumulator_preselected(p_accumulator_preselected)
  ) u_arithmetic (.op(r_op),.a(r_a),.b(r_b),.acc(r_acc),.result(o_result));
endmodule
'''


def combinational_candidate(text):
    """提取实际输入选择和算术，寄存保存关系由独立时序性质检查。"""
    capture = re.search(r"  always_ff @\(posedge clk\) begin\n    if \(i_en\) begin\n"
                        r"(.*?)\n    end\n  end\n", text, re.S)
    if capture is None:
        raise ValueError("PE 缺少共同使能的输入保存过程")
    selected = "  always_comb begin\n" + capture[1].replace("<=", "=") + "\n  end\n"
    return text.replace("module vector_pe #", "module candidate_arithmetic #", 1).replace(
        "  input wire logic clk,\n", "").replace("  input wire logic i_en,\n", "").replace(capture[0], selected)


def arithmetic_proof():
    return r'''
module arithmetic_proof #(
  parameter bit EXTENDED=1'b1, SELECTED=1'b0
)(
  input logic [2:0] i_op,
  input logic signed [15:0] i_a, i_b,
  input logic signed [31:0] i_acc,
  output logic equal
);
  wire signed [31:0] actual_result, reference_result;
  candidate_arithmetic #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_actual (
    .i_op,.i_a,.i_b,.i_acc,.o_result(actual_result));
  reference_comb_pe #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_reference (
    .op(i_op),.a(i_a),.b(i_b),.acc(i_acc),.result(reference_result));
  assign equal=actual_result==reference_result;
endmodule
'''


def state_proof():
    return r'''
module state_proof #(
  parameter bit EXTENDED=1'b1, SELECTED=1'b0
)(
  input logic clk,i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] i_a,i_b,
  input logic signed [31:0] i_acc,
  output logic equal
);
  logic [2:0] reference_op;
  logic signed [15:0] reference_a,reference_b;
  logic signed [31:0] reference_acc,selected_acc;
  always_ff @(posedge clk) if(i_en)begin
    reference_op<=i_op;reference_a<=i_a;reference_b<=i_b;reference_acc<=i_acc;
  end
  always_comb begin
    selected_acc=reference_acc;
    if(!SELECTED)case(reference_op)
      3'd4,3'd5,3'd6:selected_acc=32'sd0;
      default:begin end
    endcase
  end
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(SELECTED)) u_actual (
    .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result());
  assign equal={u_actual.op,u_actual.a,u_actual.b,u_actual.acc}==
    {reference_op,reference_a,(reference_op==3'd1 ? 16'sd1 : reference_b),selected_acc};
endmodule
'''


def run(command, log, timeout=240):
    with log.open("w") as stream:
        stream.write("$ " + shlex.join(map(str, command)) + "\n")
        stream.flush()
        result = subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"验证未通过：{log}\n" + log.read_text()[-8000:])


def formal(script, log):
    run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], log)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="caace9471dafe0236f0e2a9a40b8ddb48bdb844d")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = args.source_root.resolve() / "rtl/npu/conv/vector_pe.sv"
    source_hashes = {str(current): digest(current), str(Path(__file__)): digest(Path(__file__))}
    reference_text = args.reference_file.read_text() if args.reference_file else read_rtl_source(
        f"{args.reference}:rtl/npu/conv/vector_pe.sv", cwd=ROOT, text=True)
    reference = out / "reference.sv"
    reference.write_text(clocked_reference(reference_text))
    reference_arithmetic = out / "reference_arithmetic.sv"
    reference_arithmetic.write_text(re.search(r"module reference_comb_pe\b.*?endmodule",
                                             reference.read_text(), re.S)[0] + "\n")
    current_arithmetic = out / "current_arithmetic.sv"
    current_arithmetic.write_text(combinational_candidate(current.read_text()))
    arithmetic_model = out / "arithmetic_proof.sv"
    arithmetic_model.write_text(arithmetic_proof())
    state_model = out / "state_proof.sv"
    state_model.write_text(state_proof())
    report = dict(reference=None if args.reference_file else args.reference, source_sha256=source_hashes,
                  reference_sha256=digest(reference), input_constraints=None, runs=[])
    for extended in (0, 1):
        for selected in (0, 1):
            name = f"extended{extended}_selected{selected}"
            logs = []
            for part, paths, command in (
                ("arithmetic", [reference_arithmetic, current_arithmetic, arithmetic_model],
                 "sat -verify -prove equal 1 -show-inputs -show-outputs"),
                ("state", [current, state_model],
                 "sat -verify -seq 2 -tempinduct -maxsteps 6 -set-at 1 i_en 1 "
                 "-prove equal 1 -show-inputs -show-outputs")
            ):
                script, log = out / f"{name}_{part}.ys", out / f"{name}_{part}.log"
                script.write_text(f"read_slang --top {part}_proof -GEXTENDED={extended} "
                                  f"-GSELECTED={selected} " + shlex.join(map(str, paths)) +
                                  f"\nprep -top {part}_proof -flatten\nopt -full\n" + command + "\n")
                formal(script, log)
                logs.append(log)
            row = dict(case=name, passed=True, arithmetic_output_bits=32,
                       captured_state_bits=67, arithmetic_input_constraints=None,
                       initial_capture_enabled=True,
                       log_sha256={path.name: digest(path) for path in logs})
            report["runs"].append(row)
            print(json.dumps(row), flush=True)

    comparison = out / "preselection.sv"
    comparison.write_text(r'''
module preselection #(parameter bit EXTENDED=1'b0)(
  input logic clk, i_en,
  input logic [2:0] i_op,
  input logic signed [15:0] i_a, i_b,
  input logic signed [31:0] i_acc,
  output logic equal
);
  logic signed [31:0] selected_acc;
  wire signed [31:0] default_result, selected_result, positional_result;
  always_comb begin
    selected_acc=i_acc;
    case (i_op)
      3'd4,3'd5,3'd6: selected_acc=32'sd0;
      default: begin end
    endcase
  end
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED)) u_default (
    .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(default_result));
  vector_pe #(.ENABLE_EXTENDED_MULTIPLY(EXTENDED),.p_accumulator_preselected(1'b1)) u_selected (
    .clk,.i_en,.i_op,.i_a,.i_b,.i_acc(selected_acc),.o_result(selected_result));
  vector_pe #(EXTENDED,1'b1) u_positional (
    .clk,.i_en,.i_op,.i_a,.i_b,.i_acc(selected_acc),.o_result(positional_result));
  assign equal=default_result==selected_result && selected_result==positional_result;
endmodule
''')
    report["preselection"] = []
    for extended in (0, 1):
        script, log = out / f"preselection{extended}.ys", out / f"preselection{extended}.log"
        script.write_text("read_slang --top preselection -GEXTENDED=" + str(extended) + " " +
                          shlex.join(map(str, [current, comparison])) + "\n" +
                          "prep -top preselection -flatten\nopt -full\n" +
                          "sat -verify -seq 4 -set-at 1 i_en 1 -prove-skip 1 " +
                          "-prove equal 1 -show-inputs -show-outputs\n")
        formal(script, log)
        report["preselection"].append(dict(extended=extended, passed=True, log_sha256=digest(log)))

    ref_sim = out / "reference_sim.sv"
    ref_sim.write_text(reference.read_text().replace("module vector_pe #", "module reference_pe #", 1))
    bench = out / "four_state.sv"
    bench.write_text(r'''
module tb;
  logic clk=0, i_en=0;
  logic [2:0] i_op;
  logic signed [15:0] i_a, i_b;
  logic signed [31:0] i_acc;
  wire signed [31:0] result[4], reference_result[4];
  logic [66:0] stimulus, saved;
  logic [31:0] rng=32'h83bc7325;
  integer checks=0, samples=0, hold_checks=0;
  assign {i_op,i_a,i_b,i_acc}=stimulus;
  for(genvar configuration=0;configuration<4;configuration++) begin : g_configuration
    vector_pe #(.ENABLE_EXTENDED_MULTIPLY(configuration/2),.p_accumulator_preselected(configuration%2)) u_current (
      .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(result[configuration]));
    reference_pe #(.ENABLE_EXTENDED_MULTIPLY(configuration/2),.p_accumulator_preselected(configuration%2)) u_reference (
      .clk,.i_en,.i_op,.i_a,.i_b,.i_acc,.o_result(reference_result[configuration]));
  end
  task automatic sample(input logic enabled);
    logic [31:0] previous[4];
    for(integer configuration=0;configuration<4;configuration++) previous[configuration]=result[configuration];
    i_en=enabled;clk=0;#1;clk=1;#1;
    for(integer configuration=0;configuration<4;configuration++) begin
      if(result[configuration] !== reference_result[configuration])
        $fatal(1,"PE 四态结果不同 configuration=%0d sample=%0d",configuration,samples);
      checks++;
      if(enabled !== 1'b1) begin
        if(result[configuration] !== previous[configuration]) $fatal(1,"PE 暂停保持不同");
        hold_checks++;
      end
    end
    samples++;clk=0;#1;
  endtask
  initial begin
    stimulus='0;sample(1'b1);
    for(integer trial=0;trial<2048;trial++) begin
      for(integer bit_index=0;bit_index<67;bit_index++) begin
        rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
        stimulus[bit_index]=rng[0];
      end
      sample(1'b1);saved=stimulus;
      for(integer bit_index=0;bit_index<67;bit_index++) begin
        stimulus=saved;stimulus[bit_index]=1'bx;sample(1'b1);
        stimulus=saved;stimulus[bit_index]=1'bz;sample(1'b1);
      end
      stimulus=~saved;sample(1'b0);sample(1'bx);sample(1'bz);
    end
    $display("VECTOR_PE_FOUR_STATE_PASS samples=%0d checks=%0d hold_checks=%0d",samples,checks,hold_checks);
    $finish;
  end
endmodule
''')
    binary = out / "four_state.vvp"
    run([args.iverilog, "-g2012", "-s", "tb", "-o", binary, current, ref_sim, bench], out / "four_state_compile.log")
    run([args.vvp, binary], out / "four_state.log")
    marker = re.search(r"VECTOR_PE_FOUR_STATE_PASS (.*)", (out / "four_state.log").read_text())
    if marker is None:
        raise RuntimeError("四态检查缺少完成记录")
    report["four_state"] = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", marker[1])}
    report["four_state"]["passed"] = True
    if any(digest(Path(path)) != value for path, value in source_hashes.items()):
        raise RuntimeError("验证期间 RTL 或测试脚本发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["four_state"]), flush=True)


if __name__ == "__main__":
    main()
