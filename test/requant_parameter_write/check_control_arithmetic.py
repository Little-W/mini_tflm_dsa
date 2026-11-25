#!/usr/bin/env python3
"""检查量化装载偏移和偏置组基址的完整算术范围及四态行为。"""
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


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open("w") as stream:
        subprocess.run([str(value) for value in command], cwd=ROOT,
                       stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/requant_control_arithmetic")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    paths = [source_root / "rtl/npu/writeback/vec_requant.sv",
             source_root / "rtl/npu/top/npu_output_pipeline.sv",
             source_root / "rtl/common/parallel_prefix_add.sv"]
    hashes = {str(path.relative_to(source_root)): digest(path) for path in paths}
    content = paths[0].read_text()
    start = content.rfind("`ifdef SYNTHESIS", 0, content.index("requant_load_advance u_load_next_offset"))
    load = content[start:content.index("  assign dma_base_addr_cur", start)]
    match = re.search(r"^module requant_load_advance\b.*?^endmodule", content, re.M | re.S)
    if match is None:
        raise RuntimeError("缺少完整装载偏移加法模块")
    load_helper = match[0]
    content = paths[1].read_text()
    start = content.index("        logic unused_bias_advance_carry;")
    bias = content[start:content.index("        assign is_bias_group_base_plus", start)]
    reports = []
    profiles = [("load", 32, 1), ("load", 16, 5), ("load", 32, 5),
                ("load", 8, 17), ("load", 36, 32), ("load", 64, 36),
                ("bias", 1, 1), ("bias", 16, 5), ("bias", 32, 10),
                ("bias", 35, 17), ("bias", 64, 9)]
    for kind, width, increment in profiles:
        folder = out / f"{kind}_{width}_{increment}"
        folder.mkdir(exist_ok=True)
        result_width = 32 if kind == "load" else width
        if kind == "load":
            declarations = f"""
    localparam integer REG_WIDTH={width}, VLEN_CNT_W={increment};
    wire [31:0] load_offset = a;
    wire [VLEN_CNT_W-1:0] beats_expect = b;
    wire [31:0] load_next_offset;
{load}
    assign actual = load_next_offset;
    assign expected = load_offset + 32'(REG_WIDTH'(beats_expect));
"""
        else:
            declarations = f"""
    localparam integer p_reg_width={width}, p_is_bias_valid_w={increment};
    wire [p_reg_width-1:0] is_bias_group_base = a;
    wire [p_is_bias_valid_w-1:0] is_bias_rows_valid = b;
    wire [p_reg_width-1:0] is_bias_advance_sum;
{bias}
    assign actual = is_bias_advance_sum;
    assign expected = is_bias_group_base + p_reg_width'(is_bias_rows_valid);
"""
        source = folder / "arithmetic.sv"
        source.write_text(f"""module arithmetic(
    input wire [{result_width-1}:0] a,
    input wire [{increment-1}:0] b,
    output wire [{result_width-1}:0] actual, expected,
    output wire equal);
{declarations}
    assign equal = actual == expected;
endmodule
{load_helper if kind == "load" else ""}
""")
        script = folder / "proof.ys"
        script.write_text("read_slang -D SYNTHESIS=1 --top arithmetic " +
                          " ".join(shlex.quote(str(path)) for path in [paths[2], source]) +
                          "\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n"
                          "prep -top arithmetic -flatten\n"
                          "sat -verify -prove equal 1 -show-inputs -show-outputs\n")
        execute([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                folder / "formal.log")
        bench = folder / "tb.sv"
        bench.write_text(f"""module tb;
    reg [{result_width-1}:0] a, saved_a;
    reg [{increment-1}:0] b, saved_b;
    wire [{result_width-1}:0] actual, expected;
    wire equal;
    integer checks=0, seed=20261125;
    arithmetic dut(.*);
    task verify; begin
        #1;
        if (actual !== expected) $fatal(1,"控制算术结果不一致");
        checks++;
    end endtask
    initial begin
        seed=$urandom(seed);
        for (integer sample=0;sample<10000;sample++) begin
            a={{$urandom,$urandom}}; b={{$urandom,$urandom}};
            case (sample%5)
                0:a='0;
                1:a='1;
                2:b='0;
                3:b='1;
                default:begin end
            endcase
            verify(); saved_a=a; saved_b=b;
`ifndef SYNTHESIS
            a[sample%{result_width}]=1'bx; verify(); a=saved_a;
            b[sample%{increment}]=1'bz; verify(); b=saved_b;
`endif
        end
        $display("CONTROL_ARITHMETIC_PASS checks=%0d",checks); $finish;
    end
endmodule
""")
        for mode, defines, count in [("two_state", ["-DSYNTHESIS"], 10000),
                                      ("four_state", [], 30000)]:
            binary = folder / mode
            execute(["iverilog", "-g2012", *defines, "-s", "tb", "-o", binary,
                     paths[2], source, bench], folder / f"{mode}_compile.log")
            execute(["vvp", binary], folder / f"{mode}.log")
            if f"CONTROL_ARITHMETIC_PASS checks={count}" not in (folder / f"{mode}.log").read_text():
                raise RuntimeError("控制算术比较未完成")
        reports.append(dict(kind=kind, register_width=width, increment_width=increment,
                            input_bits=result_width+increment, passed=True,
                            two_state_comparisons=10000, four_state_comparisons=30000,
                            formal_log_sha256=digest(folder / "formal.log")))
    if hashes != {str(path.relative_to(source_root)): digest(path) for path in paths}:
        raise RuntimeError("检查期间生产源码发生变化")
    result = dict(passed=True, source_sha256=hashes, input_assumptions=[], random_seed=20261125, profiles=reports,
                  two_state_comparisons=110000, four_state_comparisons=330000)
    (out / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
