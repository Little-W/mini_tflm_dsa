#!/usr/bin/env python3
"""验证描述符空间终点的原周期保存、完整模加比较和四态传播。"""
from __future__ import annotations

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
WIDTHS = (1, 2, 5, 6, 16, 31, 32)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, log, timeout=180):
    with log.open("w") as output:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=timeout)


def model():
    return """module position_model #(parameter int p_count_width=5)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,
 input logic [31:0] i_commit_position,i_target,
 input logic [p_count_width-1:0] i_commit_rows,
 output logic [31:0] o_position,
 output logic [p_count_width-1:0] o_rows,
 output logic o_actual,o_expected,o_equivalent);
 logic [31:0] position;
 logic [p_count_width-1:0] rows;
 always_ff @(posedge clk or negedge rst_n) begin
  if(!rst_n)begin position<=0;rows<=0;end
  else if(i_configure)begin end
  else if(i_commit)begin
   if(i_invalid)begin end
   else begin position<=i_commit_position;rows<=i_commit_rows;end
  end
 end
 conv_descriptor_position #(.p_count_width(p_count_width)) u_actual(
  .clk,.rst_n,.i_configure,.i_commit,.i_invalid,.i_commit_position,.i_commit_rows,
  .i_position(position),.i_rows(rows),.i_target,.o_equal(o_actual));
 add_equal #(.p_width(32),.p_preserve_bits(1'b1)) u_expected(
  .i_a(position),.i_b(32'(rows)),.i_target,.i_carry_in(1'b0),.o_equal(o_expected));
 assign o_position=position;
 assign o_rows=rows;
 assign o_equivalent=o_actual===o_expected;
endmodule

module proof #(parameter int p_count_width=5)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,
 input logic [31:0] i_commit_position,i_target,
 input logic [p_count_width-1:0] i_commit_rows,
 output logic proven);
 logic [31:0] position;
 logic [p_count_width-1:0] rows;
 logic actual,expected,equivalent,consistent;
 position_model #(.p_count_width(p_count_width)) u_model(
  .clk,.rst_n,.i_configure,.i_commit,.i_invalid,.i_commit_position,.i_commit_rows,.i_target,
  .o_position(position),.o_rows(rows),.o_actual(actual),.o_expected(expected),.o_equivalent(equivalent));
 assign consistent=u_model.u_actual.position_end==(position+32'(rows));
 assign proven=equivalent&&consistent;
endmodule

module position_mapping #(parameter bit p_candidate=0)(
 input logic clk,rst_n,i_configure,i_commit,i_invalid,
 input logic [31:0] i_commit_position,i_target,
 input logic [4:0] i_commit_rows,
 output logic [31:0] o_position,
 output logic [4:0] o_rows,
 output logic o_equal);
 logic actual,expected,unused_equivalent;
 logic [31:0] target;
 always_ff @(posedge clk)target<=i_target;
 position_model u_model(.clk,.rst_n,.i_configure,.i_commit,.i_invalid,.i_commit_position,
  .i_commit_rows,.i_target(target),.o_position,.o_rows,.o_actual(actual),.o_expected(expected),
  .o_equivalent(unused_equivalent));
 always_ff @(posedge clk)o_equal<=p_candidate?actual:expected;
endmodule
"""


def bench(width):
    return f"""module tb;
 localparam int p_count_width={width};
 logic clk=0,rst_n=0,i_configure=0,i_commit=0,i_invalid=0;
 logic [31:0] i_commit_position=0,i_target=0,o_position;
 logic [p_count_width-1:0] i_commit_rows=0,o_rows;
 logic o_actual,o_expected,o_equivalent;
 integer checks=0,commits=0,unknown_checks=0;
 position_model #(.p_count_width(p_count_width)) dut(.*);
 task automatic check;
  #1;
  if(o_equivalent!==1'b1)$fatal(1,"Position differs width=%0d sample=%0d",p_count_width,checks);
  if((^{{i_target,o_position,o_rows}})===1'bx)unknown_checks++;
  checks++;
 endtask
 initial begin
  #1;clk=1;check();clk=0;rst_n=1;
  for(integer sample=0;sample<4096;sample++)begin
   i_configure=(sample%11==0);i_commit=(sample%3!=0);i_invalid=(sample%7==0);
   i_commit_position=$urandom;i_commit_rows=p_count_width'($urandom);
   if(sample%4==0)i_commit_position=32'hffff_fff0;
   if(sample%4==1)i_commit_position=32'd0;
   if(sample%13==0)i_commit_rows='1;
   if(sample%17==0)i_commit_rows='0;
   if(sample%19==0)i_commit_position[sample%32]=1'bx;
   if(sample%23==0)i_commit_rows[sample%p_count_width]=1'bz;
   if(sample%29==0)i_invalid=1'bx;
   if(sample%31==0)i_commit=1'bz;
   if(sample%37==0)i_configure=1'bx;
   if(sample%41==0)rst_n=0;
   #1;clk=1;#1;
   if(i_commit===1'b1&&i_configure===1'b0&&i_invalid===1'b0)commits++;
   i_target=o_position+32'(o_rows);check();
   i_target=$urandom;check();
   i_target=o_position+32'(o_rows);i_target[sample%32]=1'bx;check();
   i_target=o_position+32'(o_rows);i_target[sample%32]=1'bz;check();
   clk=0;rst_n=1;
  end
  if(commits<1000||unknown_checks<4096)$fatal(1,"Incomplete position coverage");
  $display("POSITION_CONTEXT_PASS checks=%0d commits=%0d unknown=%0d",checks,commits,unknown_checks);
  $finish;
 end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependency = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = dependency([ROOT / "rtl/npu/conv/conv_descriptor_position.sv"], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    generated = out / "model.sv"
    generated.write_text(model())
    cases = []
    for width in WIDTHS:
        name = f"rows{width}"
        script, formal = out / (name + ".ys"), out / (name + ".formal.log")
        script.write_text("read_slang --top proof -DSYNTHESIS=1 " +
                         f"-Gp_count_width={width} " + shlex.join(map(str, [*sources, generated])) +
                         "\nprep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n"
                         "sat -verify -tempinduct -seq 1 -maxsteps 4 -set-init-zero "
                         "-set-def-inputs -prove proven 1 -show-inputs -show-outputs\n")
        run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script], formal)
        if "Induction step proven: SUCCESS!" not in formal.read_text():
            raise RuntimeError(f"未完成归纳证明：{formal}")
        test, binary = out / (name + ".sv"), out / (name + ".vvp")
        test.write_text(bench(width))
        run(["iverilog", "-g2012", "-s", "tb", "-o", binary, *sources, generated, test],
            out / (name + ".compile.log"))
        simulation = out / (name + ".simulation.log")
        run(["vvp", binary], simulation)
        matched = re.search(r"POSITION_CONTEXT_PASS checks=(\d+) commits=(\d+) unknown=(\d+)",
                            simulation.read_text())
        if matched is None or int(matched[1]) != 16385:
            raise RuntimeError(f"未完成四态比较：{simulation}")
        cases.append({"row_width": width, "inductive_equivalence_passed": True,
                      "four_state_checks": int(matched[1]), "commits": int(matched[2]),
                      "unknown_checks": int(matched[3]), "formal_log_sha256": digest(formal),
                      "simulation_log_sha256": digest(simulation)})
        print("POSITION_CONTEXT_PASS", name, flush=True)
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    mapping = {side: {"top": "position_mapping", "options": ["-D", "SYNTHESIS=1", f"-Gp_candidate={value}"],
                      "sources": list(map(str, [*sources, generated])),
                      "configuration": "完整三十二位位置和参数化行数，保持描述符提交周期"}
               for side, value in (("reference", 0), ("candidate", 1))}
    (out / "mapping_cases.json").write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
    result = {"passed": True, "sources_sha256": hashes, "cases": cases,
              "four_state_checks": sum(case["four_state_checks"] for case in cases),
              "latency_preserved": True, "unrestricted_32_bit_positions": True}
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
