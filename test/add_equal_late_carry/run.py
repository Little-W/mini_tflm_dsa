#!/usr/bin/env python3
"""验证加法等值比较的末级进位选项，覆盖完整位宽及四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path("rtl/common/add_equal.sv")
WIDTHS = (1, 2, 3, 4, 5, 8, 16, 24, 28, 29, 32, 33, 48, 64)
REFERENCE = "9e3e5d6a6f47befe6c86aceacad7999923206458"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", f"{REFERENCE}:{SOURCE}"], cwd=ROOT, text=True)
    reference = out / "reference.sv"
    reference.write_text(original.replace("module add_equal #(", "module add_equal_reference #(", 1))
    model = out / "comparison.sv"
    model.write_text("""// 比较两种相邻位实现下的默认、保留中间结果和自由归并选项。
module comparison #(parameter int p_width = 29) (
    input logic [p_width-1:0] i_a, // 完整第一个操作数
    input logic [p_width-1:0] i_b, // 完整第二个操作数
    input logic [p_width-1:0] i_target, // 完整目标值
    input logic i_carry, // 最低位输入进位
    output logic [1:0] o_equivalent, // 两种结构的全部候选均保持原有四态结果
    output logic [1:0] o_arithmetic, // 两种结构均保持定宽模加等值关系
    output logic [1:0] o_reference // 两种参考结构的比较结果
);
    logic [p_width-1:0] arithmetic_sum;
    assign arithmetic_sum = p_width'(i_a + i_b + p_width'(i_carry));
    for (genvar mode = 0; mode < 2; mode++) begin : g_mode
        logic default_equal, late_kept_equal, late_free_equal;
        add_equal_reference #(.p_width(p_width), .p_preserve_bits(mode != 0)) u_reference (
            .i_a(i_a), .i_b(i_b), .i_target(i_target), .i_carry_in(i_carry),
            .o_equal(o_reference[mode]));
        add_equal #(.p_width(p_width), .p_preserve_bits(mode != 0)) u_default (
            .i_a(i_a), .i_b(i_b), .i_target(i_target), .i_carry_in(i_carry),
            .o_equal(default_equal));
        add_equal #(.p_width(p_width), .p_preserve_bits(mode != 0),
            .p_keep_bits(1'b1), .p_late_carry(1'b1)) u_late_kept (
            .i_a(i_a), .i_b(i_b), .i_target(i_target), .i_carry_in(i_carry),
            .o_equal(late_kept_equal));
        add_equal #(.p_width(p_width), .p_preserve_bits(mode != 0),
            .p_keep_bits(1'b0), .p_late_carry(1'b1)) u_late_free (
            .i_a(i_a), .i_b(i_b), .i_target(i_target), .i_carry_in(i_carry),
            .o_equal(late_free_equal));
        assign o_equivalent[mode] = (default_equal === o_reference[mode]) &&
            (late_kept_equal === o_reference[mode]) && (late_free_equal === o_reference[mode]);
        assign o_arithmetic[mode] = o_reference[mode] == (arithmetic_sum == i_target);
    end
endmodule
""")
    resolver = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]
    sources = resolver([model, reference, ROOT / SOURCE], ROOT)
    actual_sources = [path for path in sources if path.is_relative_to(ROOT / "rtl")]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in actual_sources}
    records = []
    for width in WIDTHS:
        script, log = out / f"width{width}.ys", out / f"width{width}.log"
        script.write_text(shlex.join(["read_slang", "--top", "comparison", f"-Gp_width={width}",
            *map(str, sources)]) + "\nprep -top comparison -flatten\n"
            "sat -verify -prove o_equivalent 3 -prove o_arithmetic 3\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, str(ROOT / "scripts/fpga/open_fpga_synth.py"),
                "--worker", str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                check=True, timeout=180)
        if "SUCCESS!" not in log.read_text():
            raise RuntimeError("完整位宽形式证明未完成")
        records.append({"width": width, "passed": True, "log_sha256": digest(log)})
        print(f"ADD_EQUAL_LATE_FORMAL_PASS width={width}", flush=True)
    bench = out / "tb.sv"
    bench.write_text("""// 小位宽穷举全部四态输入，较大位宽覆盖整字、逐位未知状态和模加边界。
module trial #(parameter int p_width = 29) (
    output logic o_done // 当前位宽已完成全部输入比较
);
    localparam int p_samples = p_width <= 2 ? (1 << (2*(3*p_width+1))) : 8192;
    logic [p_width-1:0] a, b, target;
    logic carry;
    logic [1:0] equal_result, arithmetic_result, reference_result;
    integer rng = 32'h6137a84d ^ p_width;
    integer zero_count = 0, one_count = 0, unknown_count = 0;
    function automatic integer random_word;
        rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
        return rng;
    endfunction
    function automatic logic four(input logic [1:0] value);
        case (value) 0:four=0; 1:four=1; 2:four=1'bx; 3:four=1'bz; endcase
    endfunction
    comparison #(.p_width(p_width)) u_compare (.i_a(a), .i_b(b), .i_target(target),
        .i_carry(carry), .o_equivalent(equal_result), .o_arithmetic(arithmetic_result),
        .o_reference(reference_result));
    initial begin
        o_done = 1'b0;
        for (integer sample = 0; sample < p_samples; sample++) begin
            if (p_width <= 2) begin
                for (integer bit_index=0; bit_index<p_width; bit_index++) begin
                    a[bit_index] = four(2'(sample >> (2*bit_index)));
                    b[bit_index] = four(2'(sample >> (2*(p_width+bit_index))));
                    target[bit_index] = four(2'(sample >> (2*(2*p_width+bit_index))));
                end
                carry = four(2'(sample >> (6*p_width)));
            end else begin
                for (integer bit_index=0; bit_index<p_width; bit_index++) begin
                    a[bit_index] = 1'(random_word());
                    b[bit_index] = 1'(random_word());
                    target[bit_index] = 1'(random_word());
                end
                carry = four(2'(sample));
                case (sample % 12)
                    0,1: begin carry=1'(sample); target=p_width'(a+b+p_width'(carry)); end
                    2: begin a='0; b='0; target='0; end
                    3: begin a='1; b='0; target='0; carry=1; end
                    4: a[(sample/12)%p_width]=1'bx;
                    5: b[(sample/12)%p_width]=1'bz;
                    6: target[(sample/12)%p_width]=1'bx;
                    7: begin a='x; b='0; target='0; end
                    8: begin a='0; b='z; target='0; end
                    9: begin a='0; b='0; target='x; end
                    10: begin a='1; b='1; target='0; end
                    default: begin a='1; b='x; target='1; end
                endcase
            end
            #1;
            if (equal_result !== 2'b11) $fatal(1,"Late carry differs width=%0d sample=%0d",p_width,sample);
            if (reference_result[0] === 1'b0) zero_count++;
            else if (reference_result[0] === 1'b1) one_count++;
            else unknown_count++;
        end
        if (zero_count==0 || one_count==0 || unknown_count==0) $fatal(1,"Coverage incomplete");
        $display("ADD_EQUAL_LATE_FOUR_STATE_PASS width=%0d samples=%0d zero=%0d one=%0d unknown=%0d",
            p_width,p_samples,zero_count,one_count,unknown_count);
        o_done = 1'b1;
    end
endmodule
module tb;
""" + f"    logic [{len(WIDTHS)-1}:0] done;\n" + "".join(
            f"    trial #(.p_width({width})) u_width{width}(.o_done(done[{index}]));\n"
            for index, width in enumerate(WIDTHS)) +
        "    initial begin wait (&done); $display(\"ADD_EQUAL_LATE_ALL_PASS\"); $finish; end\nendmodule\n")
    binary = out / "four_state.vvp"
    with (out / "compile.log").open("w") as stream:
        subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
            *map(str, sources), str(bench)], cwd=ROOT, stdout=stream,
            stderr=subprocess.STDOUT, check=True, timeout=120)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, check=True, timeout=300)
    (out / "four_state.log").write_text(result.stdout + result.stderr)
    if "ADD_EQUAL_LATE_ALL_PASS" not in result.stdout or \
            result.stdout.count("ADD_EQUAL_LATE_FOUR_STATE_PASS") != len(WIDTHS):
        raise RuntimeError("四态比较未完成")
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in actual_sources}:
        raise RuntimeError("验证期间生产源码发生变化")
    samples = sum(1 << (2*(3*width+1)) if width <= 2 else 8192 for width in WIDTHS)
    report = {"passed": True, "reference_commit": REFERENCE, "input_constraints": None,
        "source_sha256": hashes, "formal": records, "four_state_input_vectors": samples,
        "four_state_candidate_comparisons": samples * 6,
        "four_state_log_sha256": digest(out / "four_state.log")}
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(result.stdout, flush=True)


if __name__ == "__main__":
    main()
