#!/usr/bin/env python3
"""检查 CPU 实际算术表达式的四态行为与定宽运算结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / "rtl/soc/picorv32_npu.v"
    text = read_rtl_text(source)
    names = ("operand_addition", "operand_difference", "signed_difference",
             "return_address_sum", "next_cycle_count", "next_instruction_count")
    declarations = []
    for name in names:
        match = re.search(r'wire \[[^\]]+\] '
                          + re.escape(name) + r'\s*=.*?;', text, re.S)
        if not match:
            raise RuntimeError(f"没有找到实际算术表达式：{name}")
        declarations.append(match[0])
    bench = r'''module tb;
  reg [31:0] reg_op1, reg_op2, reg_pc;
  reg [63:0] count_cycle, count_instr;
  reg latched_compr, instr_sub;
  integer checks = 0;
  reg [31:0] random_state = 32'h21c7a903;
  function automatic [31:0] random_word;
    begin
      random_state = random_state ^ (random_state << 13);
      random_state = random_state ^ (random_state >> 17);
      random_state = random_state ^ (random_state << 5);
      random_word = random_state;
    end
  endfunction
  function automatic four_value(input [1:0] value);
    case (value)
      0: four_value = 1'b0;
      1: four_value = 1'b1;
      2: four_value = 1'bx;
      3: four_value = 1'bz;
    endcase
  endfunction
''' + "\n".join(declarations) + r'''
  wire [31:0] selected = instr_sub ? operand_difference[31:0] : operand_addition;
  wire [31:0] expected = instr_sub ? reg_op1 - reg_op2 : reg_op1 + reg_op2;
  task automatic check;
    begin
      #1;
      if (selected !== expected ||
          signed_difference[32] !== ($signed(reg_op1) < $signed(reg_op2)) ||
          operand_difference[32] !== (reg_op1 < reg_op2) ||
          return_address_sum !== (reg_pc + (latched_compr ? 32'd2 : 32'd4)) ||
          next_cycle_count !== (count_cycle + 64'd1) ||
          next_instruction_count !== (count_instr + 64'd1))
        $fatal(1, "CPU arithmetic mismatch checks=%0d a=%h b=%h", checks, reg_op1, reg_op2);
      checks = checks + 6;
    end
  endtask
  initial begin
    for (integer sample_i = 0; sample_i < 20000; sample_i = sample_i + 1) begin
      reg_op1 = random_word(); reg_op2 = random_word(); reg_pc = random_word();
      count_cycle = {random_word(), random_word()};
      count_instr = {random_word(), random_word()};
      latched_compr = four_value(2'(sample_i));
      instr_sub = four_value(2'(sample_i >> 2));
      check();
      for (integer bit_i = 0; bit_i < 32; bit_i = bit_i + 1) begin
        reg_op1[bit_i] = four_value(2'(random_word()));
        reg_op2[bit_i] = four_value(2'(random_word()));
        reg_pc[bit_i] = four_value(2'(random_word()));
        count_cycle[bit_i] = four_value(2'(random_word()));
        count_instr[bit_i + 32] = four_value(2'(random_word()));
      end
      check();
    end
    $display("PASS checks=%0d", checks);
    $finish;
  end
endmodule
'''
    testbench = out / "tb.sv"
    testbench.write_text(bench)
    binary = out / "simulation.vvp"
    with (out / "build.log").open("w") as log:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary), str(testbench)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    with (out / "run.log").open("w") as log:
        subprocess.run(["vvp", str(binary)], stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=60)
    result = read_rtl_text(out / "run.log")
    assert "PASS checks=240000" in result
    assert read_rtl_text(source) == text
    summary = {"passed": True, "strict_four_state": True, "checks": 240000,
               "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
               "test_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "testbench_sha256": hashlib.sha256(testbench.read_bytes()).hexdigest(),
               "log_sha256": hashlib.sha256((out / "run.log").read_bytes()).hexdigest()}
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(result.strip())


if __name__ == "__main__":
    main()
