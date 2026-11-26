#!/usr/bin/env python3
"""比较独立激活限幅模块与完整向量引擎中的原有数值及寄存行为。"""
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
REFERENCE = "685a48415e1848e108552f1bea5072636fe0b9ad"
SOURCE = "rtl/npu/conv/vector_activation_clamp.sv"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_module(original, current):
    """直接取出参考引擎的限幅表达式与上下限寄存器，保留全部中间位宽。"""
    names = (
        "q_offset_low q_minimum_before_offset q_maximum_before_offset "
        "q_rounded_fits_s9 q_before_offset_below q_before_offset_above "
        "q_offset_increment q_offset_decrement q_positive_overflow q_negative_overflow "
        "q_below_min q_above_max q_clamped_data pool_activation_min pool_activation_max "
        "avg_power_floor avg_power_result avg_div_result add_adjusted add_below_min "
        "add_above_max add_min_high_zero add_min_high_ones add_max_high_zero "
        "add_max_high_ones add_clamped"
    ).split()
    declarations = []
    for name in names:
        found = re.findall(r"^  (?:logic|wire)[^;\n]*\b" + name + r"[^;\n]*;", original, re.M)
        if len(found) != 1:
            raise RuntimeError(f"参考声明不唯一：{name}")
        declarations.extend(found)
    first = original.index("  // 配置检查保证量化偏移和激活范围为 S8")
    end = original.index("  always_comb begin\n    add_multiplier", first)
    quantized = original[first:end]
    first = original.index("  assign q_clamped_data =")
    end = original.index("  // 乘法器已完成的输出", first)
    quantized += original[first:end]
    first = original.index("  // 有效 S8 池化输入及激活范围使精确平均值保持在 [-128,127] 内。")
    end = original.index("  // 标量限幅先保存字节结果", first)
    arithmetic = original[first:end]
    replacements = {
        "q_rounded": "i_quantized_value",
        "add_rounded": "i_add_rounded_value",
        "rounding_floor[7:0]": "i_average_floor",
        "rounding_result[7:0]": "i_average_rounded",
        "avg_signed_q": "i_average_divided",
        "c.output_offset": "cfg_output_offset",
        "c.activation_min": "cfg_minimum",
        "c.activation_max": "cfg_maximum",
    }
    logic = quantized + arithmetic
    for old, new in replacements.items():
        logic = re.sub(r"(?<![A-Za-z_0-9])" + re.escape(old) + r"(?![A-Za-z_0-9])", new, logic)
    header = current[:current.index("\n);") + 3].replace(
        "module vector_activation_clamp (", "module reference_activation_clamp (")
    return header + "\n" + "\n".join(declarations) + "\n" + logic + """
  assign o_result[0] = q_clamped_data;
  assign o_result[1] = add_clamped;
  assign o_result[2] = avg_power_result;
  assign o_result[3] = avg_div_result;
endmodule
`default_nettype wire
"""


def run(command, log, *, cwd=ROOT, timeout=180):
    with log.open("w") as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(
        ["git", "show", args.reference + ":rtl/npu/conv/vector_engine.sv"], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference = out / "reference_activation_clamp.sv"
    reference.write_text(reference_module(original, current))
    worker = ROOT / "scripts/fpga/open_fpga_synth.py"
    for label, top, source in (
        ("reference", "reference_activation_clamp", reference),
        ("current", "vector_activation_clamp", ROOT / SOURCE),
    ):
        script = out / (label + ".ys")
        script.write_text("\n".join([
            "read_slang --top " + top + " " + shlex.quote(str(source)),
            "prep -top " + top + " -flatten", "opt -full", "check -assert",
            "rename -top " + label,
            "write_rtlil " + shlex.quote(str(out / (label + ".il"))),
        ]) + "\n")
        run([sys.executable, str(worker), "--worker", str(script)], out / (label + ".log"))
    proof = out / "proof.ys"
    proof.write_text("\n".join([
        "read_rtlil " + shlex.quote(str(out / "reference.il")),
        "read_rtlil " + shlex.quote(str(out / "current.il")),
        "equiv_make reference current equivalent", "hierarchy -top equivalent",
        "equiv_simple -seq 2", "equiv_induct -seq 2", "equiv_status -assert",
    ]) + "\n")
    run([sys.executable, str(worker), "--worker", str(proof)], out / "proof.log")
    bench = out / "tb.sv"
    bench.write_text("""
`timescale 1ns/1ps
// 配置允许逐周期改变，数值覆盖符号极限、舍入边界及未知位。
module tb;
  reg clk = 0;
  reg signed [31:0] cfg_output_offset, cfg_minimum, cfg_maximum;
  reg signed [63:0] i_quantized_value, i_add_rounded_value;
  reg signed [7:0] i_average_floor, i_average_rounded;
  reg signed [8:0] i_average_divided;
  wire [3:0][31:0] actual, expected;
  integer seed = 261125;
  integer checks = 0;
  vector_activation_clamp dut (.o_result(actual), .*);
  reference_activation_clamp reference (.o_result(expected), .*);
  task compare_results;
    begin
      if (actual !== expected) $fatal(1, "clamp result mismatch at check %0d", checks);
      checks = checks + 1;
    end
  endtask
  initial begin
    for (integer sample = 0; sample < 4096; sample = sample + 1) begin
      cfg_output_offset = $random(seed);
      cfg_minimum = $random(seed);
      cfg_maximum = $random(seed);
      i_quantized_value = {$random(seed), $random(seed)};
      i_add_rounded_value = {$random(seed), $random(seed)};
      i_average_floor = $random(seed);
      i_average_rounded = $random(seed);
      i_average_divided = $random(seed);
      case (sample % 8)
        0: begin i_quantized_value = 64'sh7fff_ffff_ffff_ffff; i_add_rounded_value = 255; end
        1: begin i_quantized_value = 64'sh8000_0000_0000_0000; i_add_rounded_value = -256; end
        2: begin i_quantized_value = sample - 2048; i_add_rounded_value = sample - 2048; end
        3: begin cfg_minimum = -128; cfg_maximum = 127; end
        4: i_quantized_value[sample % 64] = 1'bx;
        5: cfg_output_offset[sample % 32] = 1'bz;
        6: begin cfg_minimum[sample % 32] = 1'bx; i_average_divided[sample % 9] = 1'bx; end
        7: begin i_add_rounded_value[sample % 64] = 1'bx; i_average_floor[sample % 8] = 1'bz; end
      endcase
      #1; compare_results();
      clk = 1;
      #1; compare_results();
      clk = 0;
      #1;
    end
    $display("PASS checks=%0d", checks);
    $finish;
  end
endmodule
""")
    executable = out / "test.vvp"
    run(["iverilog", "-g2012", "-s", "tb", "-o", str(executable), str(bench),
         str(reference), str(ROOT / SOURCE)], out / "compile.log")
    run(["vvp", str(executable)], out / "four_state.log")
    match = re.search(r"PASS checks=(\d+)", (out / "four_state.log").read_text())
    if match is None:
        raise RuntimeError(str(out / "four_state.log"))
    result = {
        "passed": True,
        "reference_commit": args.reference,
        "unbounded_equivalence": True,
        "input_assumptions": [],
        "four_state_checks": int(match[1]),
        "source_sha256": digest(ROOT / SOURCE),
        "reference_source_sha256": hashlib.sha256(original.encode()).hexdigest(),
        "proof_log_sha256": digest(out / "proof.log"),
        "four_state_log_sha256": digest(out / "four_state.log"),
    }
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
