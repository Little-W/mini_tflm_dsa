#!/usr/bin/env python3
"""验证顶层容量与预取地址的实际算术表达式及四态结果。"""
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
SOURCE = "rtl/npu/top/npu_top.sv"
OUTPUTS = {"rhs_product_high_sum": 24, "rhs_product_high_merged": 24,
           "conv_input_high_merged": 16, "conv_kernel_high_merged": 16,
           "conv_group_end": 32, "active_ps_pool_bytes": 32,
           "relative_address_sum": 32, "prefetch_address_sum": 32}
INPUTS = {"rhs_product_diagonal": 64, "rhs_product_cross": 33,
          "rhs_product_high_q": 24, "rhs_product_middle_q": 25,
          "conv_input_high": 32, "conv_kernel_high": 32,
          "conv_input_middle_q": 17, "conv_kernel_middle_q": 17,
          "cfg_group_offset": 16, "cfg_group_c": 16, "shared_ia_banks_q": 32,
          "product_high": 16, "product_low_half": 16, "offset_s1": 32,
          "base_s2": 32, "relative_address": 32, "packed_s1": 1, "wide_s1": 1}


def match(pattern, text):
    result = re.search(pattern, text, re.S)
    if result is None:
        raise ValueError("无法提取实际顶层算术表达式")
    return result[1].strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="0097b66e")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    reference = subprocess.check_output(["git", "show", args.reference + ":" + SOURCE],
                                        cwd=ROOT, text=True)
    old = {
        "rhs_product_high_sum": match(r"rhs_product_high_q\s*<=\s*(.*?);", reference),
        "rhs_product_high_merged": match(r"rhs_allocation_bytes\s*<=\s*\{\s*\((.*?)\),", reference),
        "conv_input_high_merged": match(r"conv_input_bytes\s*<=\s*\{\s*\((.*?)\),", reference),
        "conv_kernel_high_merged": match(r"conv_kernel_elements\s*<=\s*\{\s*\((.*?)\),", reference),
        "conv_group_end": match(r"\((32'\(conv_cfg_q.group_offset\)\s*\+\s*32'\(conv_cfg_q.group_c\))\s*>", reference),
        "active_ps_pool_bytes": match(r"\bactive_ps_pool_bytes\s*=\s*(.*?);", reference),
        "relative_address_sum": match(r"\brelative_address\s*<=\s*(.*?);", reference),
        "prefetch_address_sum": match(r"\bweight_prefetch_base\s*<=\s*(.*?);", reference),
    }
    new = {name: match(r"\b" + name + r"\s*=\s*(.*?);", current) for name in OUTPUTS}
    package = (ROOT / "rtl/npu/conv/conv_im2col_pkg.sv").read_text()
    if "logic [15:0] group_c, group_offset;" not in package:
        raise ValueError("卷积组字段宽度发生变化")
    def fields(text):
        return text.replace("conv_cfg_q.group_offset", "cfg_group_offset").replace(
            "conv_cfg_q.group_c", "cfg_group_c")
    input_width, output_width = sum(INPUTS.values()), sum(OUTPUTS.values())
    declarations = "\n".join(f"    wire [{width-1}:0] {name};" for name, width in INPUTS.items())
    expressions = []
    for label, values in [("expected", old), ("actual", new)]:
        for name, width in OUTPUTS.items():
            expressions.append(f"    wire [{width-1}:0] {label}_{name} = {fields(values[name])};")
        expressions.append(f"    assign {label} = {{" +
                           ",".join(label + "_" + name for name in OUTPUTS) + "};")
    model = out / "top_arithmetic.sv"
    model.write_text(f"""module top_arithmetic #(
    parameter integer SIZE_SHIFT=4, SHARED_RAM_ENABLED=1,
    SHARED_TOTAL_BYTES=57344, SHARED_BANK_BYTES=8192
)(input wire [{input_width-1}:0] inputs,
  output wire [{output_width-1}:0] expected, actual,
  output wire correct);
{declarations}
    assign {{{','.join(INPUTS)}}} = inputs;
""" + "\n".join(expressions) + "\n    assign correct = actual == expected;\nendmodule\n")
    report = {"passed": False, "reference": args.reference, "inputs_constrained": False,
              "source_sha256": hashlib.sha256(current.encode()).hexdigest(),
              "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(), "runs": []}
    for index, (shift, enabled, total, bank) in enumerate(
            [(2, 0, 32768, 4096), (2, 1, 32768, 4096),
             (4, 1, 57344, 8192), (5, 1, 65536, 8192), (6, 1, 131072, 16384)]):
        options = [f"-GSIZE_SHIFT={shift}", f"-GSHARED_RAM_ENABLED={enabled}",
                   f"-GSHARED_TOTAL_BYTES={total}", f"-GSHARED_BANK_BYTES={bank}"]
        script, log = out / f"profile{index}.ys", out / f"profile{index}.log"
        define = " -D GEMMORA_PS_POOL_BYTES=49152 "
        script.write_text("read_slang --top top_arithmetic" + define +
                          shlex.join([*options, str(model)]) +
                          "\nprep -top top_arithmetic -flatten\n"
                          "sat -verify -prove correct 1 -show-inputs -show-outputs\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                            "--worker", str(script)], stdout=stream, stderr=subprocess.STDOUT,
                           cwd=ROOT, check=True, timeout=60)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError("顶层算术证明未完成")
        bench = out / f"profile{index}_tb.sv"
        bench.write_text(f"""module tb;
    logic [{input_width-1}:0] inputs;
    wire [{output_width-1}:0] expected, actual;
    wire correct;
    integer sample, bit_index;
    logic [31:0] random_state=32'h6b27dc15;
    top_arithmetic #(.SIZE_SHIFT({shift}),.SHARED_RAM_ENABLED({enabled}),
        .SHARED_TOTAL_BYTES({total}),.SHARED_BANK_BYTES({bank})) dut (.*);
    initial begin
        for(sample=0;sample<8192;sample++) begin
            for(bit_index=0;bit_index<{input_width};bit_index++) begin
                random_state=random_state^(random_state<<13);
                random_state=random_state^(random_state>>17);
                random_state=random_state^(random_state<<5);
                case(random_state[4:0])
                    0:inputs[bit_index]=1'bx;
                    1:inputs[bit_index]=1'bz;
                    default:inputs[bit_index]=random_state[0];
                endcase
            end
            #1;
            if(actual !== expected)$fatal(1,"top arithmetic mismatch sample=%0d",sample);
        end
        $display("TOP_ARITHMETIC_PASS checks=8192");$finish;
    end
endmodule
""")
        binary, simulation_log = out / f"profile{index}_simulation", out / f"profile{index}_four_state.log"
        with simulation_log.open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-DGEMMORA_PS_POOL_BYTES=49152", "-s", "tb",
                            "-o", str(binary), str(model), str(bench)], stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
            subprocess.run(["vvp", str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=60)
        result = simulation_log.read_text()
        if "TOP_ARITHMETIC_PASS checks=8192" not in result or re.search(r"ERROR:|FATAL:", result):
            raise RuntimeError("顶层四态算术比较未完成")
        report["runs"].append({"size_shift": shift, "shared_enabled": enabled,
                               "shared_total_bytes": total, "shared_bank_bytes": bank,
                               "passed": True, "four_state_checks": 8192,
                               "formal_log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                               "four_state_log_sha256": hashlib.sha256(simulation_log.read_bytes()).hexdigest()})
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间顶层源文件发生变化")
    report["passed"] = True
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
