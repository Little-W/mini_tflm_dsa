#!/usr/bin/env python3
"""验证偏置配置的完整定宽表达式、四态结果和配置保存结构。"""
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
RELATIVE = "rtl/npu/top/npu_output_pipeline.sv"
NAMES = (
    "is_bias_group_rows_target_ext", "is_bias_rows_fit", "is_bias_rows_less",
    "is_bias_rows_equal", "is_bias_exec_m_ext", "is_bias_mask_group_zero",
    "is_bias_high_group_zero", "is_bias_target_mask_ext", "is_bias_low_difference",
    "is_bias_full_group_base", "is_bias_tail_rows_raw", "is_bias_tail_rows_calc",
    "is_bias_last_group_base_calc", "is_bias_first_rows_valid")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run([str(value) for value in command], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=180)


def save_block(content):
    anchor = content.index("                is_bias_group_base <= '0;")
    first = content.rfind("        always_ff", 0, anchor)
    last = content.index("    logic signed [31:0] bias_rhs", anchor)
    return re.sub(r"\s+", "", content[first:last])


def module(content, name, width, valid):
    count = min(width, valid)
    declarations = []
    for identifier in NAMES:
        match = re.search(r"^.*\blogic\b[^\n;]*\b" + identifier + r";", content, re.M)
        if match is None:
            raise RuntimeError("缺少配置算术信号：" + identifier)
        declarations.append(match[0])
    start = content.index("    assign is_bias_group_rows_target_ext =")
    finish_match = re.search(r"^\s*(?:logic unused_bias_advance_carry;|npu_output_bias_advance\s*#)",
                             content[start:], re.M)
    if finish_match is None:
        raise RuntimeError("缺少偏置配置与分组推进之间的模块边界")
    finish = start+finish_match.start()
    extra = content[content.index("endmodule") + len("endmodule"):]
    return f"""module {name}(
    input wire [31:0] i_exec_m,
    input wire [{valid-1}:0] i_is_bias_group_rows_target,
    output wire [{4*width+2*valid}:0] result);
    localparam integer p_reg_width={width}, p_is_bias_valid_w={valid};
    localparam integer p_bias_compare_width={max(width,32)}, p_bias_count_bits={count};
    localparam integer p_bias_mask_groups={(count+3)//4};
    localparam integer p_bias_high_groups={(width-count+3)//4};
{chr(10).join(declarations)}
{content[start:finish]}
    assign result = {{is_bias_target_mask_ext, is_bias_full_group_base,
        is_bias_tail_rows_raw, is_bias_last_group_base_calc,
        is_bias_tail_rows_calc, is_bias_first_rows_valid, is_bias_rows_fit}};
endmodule
{extra}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate_path = args.source_root.resolve() / RELATIVE
    reference_path = args.reference_root.resolve() / RELATIVE
    candidate, reference = candidate_path.read_text(), reference_path.read_text()
    if save_block(candidate) != save_block(reference):
        raise RuntimeError("配置寄存器的复位或更新结构发生变化")
    common = args.source_root.resolve() / "rtl/common/unsigned_compare.sv"
    helper = args.source_root.resolve() / "rtl/npu/top/npu_output_bias_mask.sv"
    helpers = [common, helper] if helper.is_file() else [common]
    reports = []
    for width, valid in [(1,1),(4,3),(8,5),(16,9),(32,9),(32,10),(32,16),(32,32),(35,17),(64,9)]:
        folder = out / f"register{width}_target{valid}"
        folder.mkdir(exist_ok=True)
        result_width = 4*width+2*valid+1
        gate, gold = folder/"candidate.sv", folder/"reference.sv"
        gate.write_text(module(candidate, "candidate", width, valid))
        gold.write_text(module(reference, "reference", width, valid))
        checker = folder/"configuration.sv"
        checker.write_text(f"""module configuration(
    input wire [31:0] i_exec_m,
    input wire [{valid-1}:0] i_is_bias_group_rows_target,
    output wire [{result_width-1}:0] actual, original, expected,
    output wire equal);
    candidate u_candidate(.i_exec_m(i_exec_m),
        .i_is_bias_group_rows_target(i_is_bias_group_rows_target), .result(actual));
    reference u_reference(.i_exec_m(i_exec_m),
        .i_is_bias_group_rows_target(i_is_bias_group_rows_target), .result(original));
    wire [{width-1}:0] target = {width}'(i_is_bias_group_rows_target);
    wire [{width-1}:0] dimension = {width}'(i_exec_m);
    wire [{width-1}:0] mask = target - {width}'(1);
    wire [{width-1}:0] difference = dimension - target;
    wire [{width-1}:0] tail = dimension & mask;
    wire fits = {max(width,32)}'(i_exec_m) <= {max(width,32)}'(target);
    wire [{valid-1}:0] last_rows = tail == '0 ? i_is_bias_group_rows_target : {valid}'(tail);
    wire [{width-1}:0] last_base = fits ? '0 : tail == '0 ? difference :
        dimension & ~{width}'({valid}'(mask));
    wire [{valid-1}:0] first_rows = i_exec_m == '0 ? {valid}'(1) :
        !fits ? i_is_bias_group_rows_target : {valid}'(i_exec_m);
    assign expected = {{mask, difference, tail, last_base, last_rows, first_rows, fits}};
    assign equal = (actual == expected) && (actual == original);
endmodule
""")
        script = folder/"proof.ys"
        script.write_text("read_slang -DSYNTHESIS=1 --top configuration " +
            shlex.join(map(str,helpers+[gate,gold,checker])) +
            "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
            "prep -top configuration -flatten\n"
            "sat -verify -prove equal 1 -show-inputs -show-outputs\n")
        execute([sys.executable,ROOT/"scripts/fpga/open_fpga_synth.py","--worker",script],folder/"formal.log")
        bench = folder/"tb.sv"
        bench.write_text(f"""module tb;
    reg [31:0] i_exec_m, saved_m;
    reg [{valid-1}:0] i_is_bias_group_rows_target, saved_target;
    wire [{result_width-1}:0] actual, original, expected;
    wire equal;
    integer checks=0, seed=20261125;
    configuration dut(.*);
    task verify; begin
        #1;
        if(actual !== original) $fatal(1,"偏置配置的四态结果不一致");
        checks++;
    end endtask
    initial begin
        seed=$urandom(seed);
        for(integer sample=0;sample<10000;sample++) begin
            i_exec_m=$urandom;
            i_is_bias_group_rows_target=$urandom;
            case(sample%8)
                0:i_exec_m='0;
                1:i_exec_m='1;
                2:i_is_bias_group_rows_target='0;
                3:i_is_bias_group_rows_target='1;
                4:i_exec_m=32'(i_is_bias_group_rows_target);
                5:i_exec_m=32'(i_is_bias_group_rows_target)+32'd1;
                6:i_exec_m=32'(i_is_bias_group_rows_target)-32'd1;
                default:begin end
            endcase
            verify(); saved_m=i_exec_m; saved_target=i_is_bias_group_rows_target;
            i_is_bias_group_rows_target[sample%{valid}]=1'bx; verify();
            i_is_bias_group_rows_target=saved_target;
            i_exec_m[sample%32]=1'bz;verify();i_exec_m=saved_m;
        end
        $display("BIAS_CONFIGURATION_PASS checks=%0d",checks);$finish;
    end
endmodule
""")
        binary=folder/"simulation"
        execute(["iverilog","-g2012","-s","tb","-o",binary,*helpers,gate,gold,checker,bench],folder/"compile.log")
        execute(["vvp",binary],folder/"simulation.log")
        if "BIAS_CONFIGURATION_PASS checks=30000" not in (folder/"simulation.log").read_text():
            raise RuntimeError("偏置配置的四态检查未完成")
        reports.append({"register_width":width,"target_width":valid,"passed":True,
            "input_bits":32+valid,"output_bits":result_width,"four_state_comparisons":30000,
            "formal_log_sha256":sha(folder/"formal.log"),"simulation_log_sha256":sha(folder/"simulation.log")})
    if candidate_path.read_text()!=candidate or reference_path.read_text()!=reference:
        raise RuntimeError("验证期间源文件发生变化")
    report={"passed":True,"source_sha256":sha(candidate_path),
        "reference_sha256":sha(reference_path),"input_assumptions":[],
        "configuration_updates_unchanged":True,"random_seed":20261125,
        "profiles":reports,"four_state_comparisons":sum(r["four_state_comparisons"] for r in reports)}
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"passed":True,"profiles":len(reports),"four_state_comparisons":report["four_state_comparisons"]}))


if __name__=="__main__":
    main()
