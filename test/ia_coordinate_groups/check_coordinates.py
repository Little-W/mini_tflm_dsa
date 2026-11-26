#!/usr/bin/env python3
"""检查完整坐标比较、配置选择和高位加一的二态及四态行为。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from run_formal import ROOT, REFERENCE, HELPER, UPDATE, digest
from scripts.rtl.source_files import input_files, with_dependencies

CASES = ((1, 0), (2, 1), (3, 1), (4, 2), (7, 0), (8, 3), (16, 4),
         (17, 5), (29, 4), (32, 4), (32, 0), (48, 5), (64, 4))
MODEL = """
module miter #(parameter integer p_width=32, p_low_width=4) (
    input logic i_update,
    input logic [p_width-1:0] i_base, i_next_base, i_offset,
    output wire o_equal,
    output wire [2:0] o_reference, o_candidate
);
    localparam integer p_high_width=p_width-p_low_width;
    wire [p_width-1:0] selected_base=i_update ? i_next_base : i_base;
    reference_same #(.p_width(p_width),.p_low_width(p_low_width)) u_original_same (
        .i_base_a(i_base),.i_base_b(i_next_base),.i_offset,.o_equal(o_reference[0]));
    reference_same #(.p_width(p_width),.p_low_width(p_low_width)) u_original_update (
        .i_base_a(i_base),.i_base_b(selected_base),.i_offset,.o_equal(o_reference[1]));
    add_equal #(.p_width(p_high_width),.p_preserve_bits(1'b1)) u_original_increment (
        .i_a(i_base[p_width-1:p_low_width]),.i_b(p_high_width'(0)),
        .i_carry_in(1'b1),.i_target(i_next_base[p_width-1:p_low_width]),
        .o_equal(o_reference[2]));
    ia_ordered_coordinate_same #(.p_width(p_width),.p_low_width(p_low_width)) u_same (
        .i_base_a(i_base),.i_base_b(i_next_base),.i_offset,.o_equal(o_candidate[0]));
    ia_ordered_coordinate_update #(.p_width(p_width),.p_low_width(p_low_width)) u_update (
        .i_update,.i_base,.i_next_base,.i_offset,.o_equal(o_candidate[1]));
    increment_equal #(.p_width(p_high_width),.p_preserve_pairs(1'b1),.p_reduce_group_width(6)) u_increment (
        .i_a(i_base[p_width-1:p_low_width]),.i_target(i_next_base[p_width-1:p_low_width]),
        .o_equal(o_candidate[2]));
    assign o_equal=o_reference==o_candidate;
endmodule
"""
BENCH = """
module tb;
    parameter integer p_width=32,p_low_width=4;
    localparam integer bits_count=3*p_width+1;
    logic i_update;
    logic [p_width-1:0] i_base,i_next_base,i_offset;
    logic [bits_count-1:0] symbols;
    wire [2:0] o_reference,o_candidate;
    wire o_equal;
    integer checks=0;
    miter #(.p_width(p_width),.p_low_width(p_low_width)) dut(.*);
    task compare;
        #1;
        if(o_reference!==o_candidate)
            $fatal(1,"coordinate comparison differs update=%b base=%h next=%h offset=%h ref=%b result=%b",
                i_update,i_base,i_next_base,i_offset,o_reference,o_candidate);
        checks++;
    endtask
    initial begin
        if(p_width<=3) begin
            for(integer value=0;value<(1<<(2*bits_count));value++)begin
                for(integer bit_index=0;bit_index<bits_count;bit_index++)begin
                    case((value>>(2*bit_index))&3)
                        0:symbols[bit_index]=1'b0;
                        1:symbols[bit_index]=1'b1;
                        2:symbols[bit_index]=1'bx;
                        3:symbols[bit_index]=1'bz;
                    endcase
                end
                {i_update,i_base,i_next_base,i_offset}=symbols;compare();
            end
        end else begin
            for(integer sample=0;sample<24576;sample++)begin
                i_base=p_width'({$urandom,$urandom});
                i_next_base=p_width'({$urandom,$urandom});
                i_offset=p_width'({$urandom,$urandom});
                case(sample%4)
                    0:i_update=1'b0;1:i_update=1'b1;2:i_update=1'bx;3:i_update=1'bz;
                endcase
                case(sample%8)
                    0:i_next_base=i_base;
                    1:i_next_base=i_base+p_width'(1<<p_low_width);
                    2:i_next_base=i_base-p_width'(1<<p_low_width);
                    3:i_offset='0;
                    4:begin i_base='1;i_next_base='0;i_offset='1;end
                    5:i_base[$urandom_range(0,p_width-1)]=1'bx;
                    6:i_next_base[$urandom_range(0,p_width-1)]=1'bz;
                    7:i_offset[$urandom_range(0,p_width-1)]=1'bx;
                endcase
                compare();
            end
        end
        $display("IA_COORDINATE_FOUR_STATE_PASS checks=%0d comparisons=%0d",checks,3*checks);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(["git", "show", args.reference + ":" + str(HELPER)], cwd=ROOT, text=True)
    design = out / "miter.sv"
    design.write_text(re.sub(r"\bia_ordered_coordinate_same\b", "reference_same", original) + MODEL)
    bench = out / "tb.sv"
    bench.write_text(BENCH)
    dependencies = with_dependencies([ROOT / HELPER, ROOT / UPDATE], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in input_files(dependencies, ROOT)}
    sources = [design, *dependencies]

    def verify(job):
        width, low, fpga = job
        label = f"width{width}_low{low}_" + ("fpga" if fpga else "generic")
        folder = out / label
        folder.mkdir(exist_ok=True)
        flags = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else ["-USYNTHESIS", "-UXILINX_FPGA"]
        script, log = folder / "proof.ys", folder / "proof.log"
        script.write_text("\n".join([
            "read_slang --top miter " + shlex.join(flags + [f"-Gp_width={width}", f"-Gp_low_width={low}"] + list(map(str,sources))),
            "setattr -mod -unset keep_hierarchy", "setattr -unset keep_hierarchy",
            "prep -top miter -flatten", "sat -verify -prove o_equal 1 -show-inputs -show-outputs",
        ]) + "\n")
        with log.open("w") as stream:
            subprocess.run([sys.executable, ROOT / "scripts/fpga/open_fpga_synth.py", "--worker", script],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        if "SAT proof finished - no model found: SUCCESS!" not in log.read_text():
            raise RuntimeError(label)
        binary = folder / "four_state.vvp"
        with (folder / "compile.log").open("w") as stream:
            subprocess.run(["iverilog", "-g2012", "-s", "tb", f"-Ptb.p_width={width}",
                            f"-Ptb.p_low_width={low}", *(["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if fpga else []),
                            "-o", str(binary), *map(str, sources), str(bench)],
                           cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(["vvp", str(binary)], cwd=ROOT, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        (folder / "four_state.log").write_text(result.stdout)
        if result.returncode or "IA_COORDINATE_FOUR_STATE_PASS" not in result.stdout:
            raise RuntimeError(result.stdout)
        counts = {name:int(value) for name,value in re.findall(r"(\w+)=(\d+)",result.stdout)}
        row = dict(width=width,low_width=low,fpga=fpga,passed=True,formal=True,
                   four_state=counts,proof_log_sha256=digest(log),binary_sha256=digest(binary))
        print(json.dumps(row),flush=True)
        return row

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        rows = list(pool.map(verify, ((width,low,fpga) for width,low in CASES for fpga in (False,True))))
    if hashes != {name:digest(ROOT/name) for name in hashes}:
        raise RuntimeError("验证期间 RTL 内容发生变化")
    summary = dict(passed=True,reference=args.reference,source_sha256=hashes,
                   input_constraints=None,profiles=rows,
                   four_state_comparisons=sum(row["four_state"]["comparisons"] for row in rows))
    (out/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")


if __name__ == "__main__":
    main()
