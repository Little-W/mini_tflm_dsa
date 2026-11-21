#!/usr/bin/env python3
"""检查 FIFO 配置保存、背压与末拍状态在四态输入下的逐周期行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from run_formal import ROOT, SOURCE, read_rtl_source


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default="415a70a")
    parser.add_argument("--reference-file", type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / SOURCE).read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    models = []
    fields = ("active_read_count_q", "vec_valid_num_col_tmp", "vec_valid_num_row_tmp",
              "transpose_mode_tmp", "last_beat_idx_q")
    for label, text in (("reference", reference), ("current", source)):
        text = text[:text.index("module vec_s8_to_fifo_linear")]
        block = text[text.index("  always @(posedge clk) begin"):
                     text.index("  integer valid_cols_i;")]
        # 保留实际过程块中的全部条件及目标寄存器赋值，其他状态作为任意输入。
        block = re.sub(r"\b(\w+)\s*<=\s*[^;]+;",
                       lambda match: match[0] if match[1] in fields else "begin end", block)
        function = re.search(r"  function automatic \[COUNT_WIDTH-1:0\] last_beat_index.*?endfunction",
                             text, re.S)
        index = re.search(r"  wire \[COUNT_WIDTH-1:0\] last_beat_idx_cur\s*=.*?;", text, re.S)[0]
        model = f"""module {label}_state #(parameter VLEN=16,BUS_WIDTH=64)(
    input logic clk,rst_n,coalesce_enable,finish_write_bank,write_bank_blocked,in_valid,
    input logic output_fire,last_row_in_bank,co_start,co_fire,co_group_last,
    input logic co_continue_bank_ready,co_load_waiting,co_finish,start_stream,
    input logic stream_active,output_ready,last_beat_in_row,transpose_mode_eff,
    input logic [$clog2(VLEN)-1:0] read_ptr,beat_idx,vec_valid_num_col,vec_valid_num_row,
    input logic [$clog2(VLEN+1)-1:0] read_bank_count,
    output logic [$clog2(VLEN+1)-1:0] active_read_count_q,
    output logic [$clog2(VLEN)-1:0] vec_valid_num_col_tmp,vec_valid_num_row_tmp,
    output logic transpose_mode_tmp,
    output wire [$clog2(VLEN+1)-1:0] last_beat_index_value
);
    localparam COUNT_WIDTH=$clog2(VLEN+1), BYTE_SHIFT=$clog2(BUS_WIDTH/8);
    logic [COUNT_WIDTH-1:0] last_beat_idx_q;
    wire [COUNT_WIDTH-1:0] active_read_count=active_read_count_q;
    wire [COUNT_WIDTH-1:0] output_col_count=transpose_mode_tmp ? active_read_count :
        COUNT_WIDTH'(vec_valid_num_col_tmp)+COUNT_WIDTH'(1);
{function[0] if function else ''}
{index}
{block}
    assign last_beat_index_value=last_beat_idx_cur;
endmodule
"""
        path = out / f"{label}.sv"
        path.write_text(model)
        models.append(path)
    bench = r"""module state_pair #(parameter VLEN=16,BUS_WIDTH=64)(
    input logic clk,rst_n,input logic [31:0] controls,counts,output logic o_equal
);
    wire [$clog2(VLEN+1)-1:0] active_read_count_q[2],last_beat_index_value[2];
    wire [$clog2(VLEN)-1:0] vec_valid_num_col_tmp[2],vec_valid_num_row_tmp[2];
    wire transpose_mode_tmp[2];
"""
    names = ("coalesce_enable,finish_write_bank,write_bank_blocked,in_valid,output_fire,"
             "last_row_in_bank,co_start,co_fire,co_group_last,co_continue_bank_ready,"
             "co_load_waiting,co_finish,start_stream,stream_active,output_ready,"
             "last_beat_in_row,transpose_mode_eff").split(",")
    for index, label in enumerate(("reference", "current")):
        connections = ",".join(f".{name}(controls[{bit}])" for bit,name in enumerate(names))
        bench += f"""
    {label}_state #(.VLEN(VLEN),.BUS_WIDTH(BUS_WIDTH)) u_{label}(
        .clk,.rst_n,{connections},.read_ptr(counts[0+:$clog2(VLEN)]),
        .beat_idx(counts[6+:$clog2(VLEN)]),.vec_valid_num_col(counts[12+:$clog2(VLEN)]),
        .vec_valid_num_row(counts[18+:$clog2(VLEN)]),.read_bank_count(counts[24+:$clog2(VLEN+1)]),
        .active_read_count_q(active_read_count_q[{index}]),
        .vec_valid_num_col_tmp(vec_valid_num_col_tmp[{index}]),
        .vec_valid_num_row_tmp(vec_valid_num_row_tmp[{index}]),
        .transpose_mode_tmp(transpose_mode_tmp[{index}]),
        .last_beat_index_value(last_beat_index_value[{index}]));
"""
    bench += r"""
    assign o_equal=(active_read_count_q[0] === active_read_count_q[1]) &&
        (vec_valid_num_col_tmp[0] === vec_valid_num_col_tmp[1]) &&
        (vec_valid_num_row_tmp[0] === vec_valid_num_row_tmp[1]) &&
        (transpose_mode_tmp[0] === transpose_mode_tmp[1]) &&
        (last_beat_index_value[0] === last_beat_index_value[1]);
endmodule
module tb;
    logic clk=0,rst_n=0;
    logic [31:0] controls=0,counts=0,random_state=32'h29e1b713;
    integer cycle,bit_index;
    function automatic logic symbol(input logic [4:0] value);
        case(value)
            5'd0: symbol=1'bx;
            5'd1: symbol=1'bz;
            default: symbol=value[0];
        endcase
    endfunction
    task automatic advance_random;
        random_state=random_state ^ (random_state << 13);
        random_state=random_state ^ (random_state >> 17);
        random_state=random_state ^ (random_state << 5);
    endtask
"""
    profiles=[(8,32),(8,64),(16,32),(16,64),(16,128),(32,32),(32,64)]
    for index,(vlen,bus) in enumerate(profiles):
        bench += f"""
    wire equal_{index};
    state_pair #(.VLEN({vlen}),.BUS_WIDTH({bus})) u_pair_{index}(
        .clk,.rst_n,.controls,.counts,.o_equal(equal_{index}));
    always @(negedge clk) begin
        if(equal_{index} !== 1'b1)
            $fatal(1,"FIFO state mismatch profile={index} cycle=%0d",cycle);
    end
"""
    bench += r"""
    initial begin
        #1;clk=1;#1;clk=0;#1;
        for(cycle=0;cycle<20000;cycle=cycle+1) begin
            advance_random();
            rst_n=(cycle%257==0)?1'b0:((cycle%97==0)?symbol(random_state[4:0]):1'b1);
            for(bit_index=0;bit_index<32;bit_index=bit_index+1) begin
                advance_random();controls[bit_index]=symbol(random_state[4:0]);
                advance_random();counts[bit_index]=symbol(random_state[4:0]);
            end
            if(cycle%16 < 8) begin
                controls[0]=0;controls[12]=0;controls[13]=1;controls[14]=0;
                counts[0+:6]=0;counts[6+:6]=0;
            end
            #1;clk=1;#1;clk=0;#1;
        end
        $display("FIFO_LAST_BEAT_FOUR_STATE_PASS cycles=20000 profiles=7 comparisons=700000");
        $finish;
    end
endmodule
"""
    testbench = out / "tb.sv"
    testbench.write_text(bench)
    binary = out / "simulation"
    command = ["iverilog", "-g2012", "-s", "tb", "-o", str(binary), *map(str, models), str(testbench)]
    with (out / "compile.log").open("w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(["vvp", str(binary)], capture_output=True, text=True, timeout=300)
    (out / "run.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    if "FIFO_LAST_BEAT_FOUR_STATE_PASS" not in result.stdout:
        raise RuntimeError("四态比较未完成")
    if source != (ROOT / SOURCE).read_text():
        raise RuntimeError("验证期间源码发生变化")
    report = dict(passed=True, cycles=20000, profiles=profiles, comparisons=700000,
                  source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                  reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  testbench_sha256=digest(testbench), log_sha256=digest(out / "run.log"))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
