#!/usr/bin/env python3
"""检查计数存储、银行有效位与读取资格在四态输入下的逐周期行为。"""
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


def model(source: str, label: str) -> str:
    """直接提取计数存储、银行状态过程及读取资格表达式。"""
    declarations = source[source.index("  logic bank_count_i_wr_en;"):
                          source.index("\n\n  logic co_group_last_result;")]
    selection = ""
    if "  logic selected_read_bank_ready;" in source:
        selection = source[source.index("  logic selected_read_bank_ready;"):
                           source.index("  if (p_count_storage) begin : g_count_memory")]
    storage = source[source.index("  if (p_count_storage) begin : g_count_memory"):
                     source.index("  wire [COUNT_WIDTH-1:0] active_read_count =")]
    if "  logic read_bank_ready;" in source:
        qualification = source[source.index("  logic read_bank_ready;"):
                               source.index("  function automatic [COUNT_WIDTH-1:0] last_beat_index(")]
    else:
        qualification = re.search(r"  wire read_bank_ready = .*?;", source, re.S)[0]
    start = source.index("  for (genvar bank = 0; bank < BANKS; bank++) begin : g_bank_state")
    state = source[start:source.index("\n  always @(posedge clk) begin", start)]
    raw_nonempty = "(g_count_memory.u_bank_count.mem[bank] != '0)"
    return f"""module {label}_count #(
    parameter VLEN=16, BANKS=32,
    parameter BANK_WIDTH=(BANKS<=1)?1:$clog2(BANKS),
    parameter COUNT_WIDTH=$clog2(VLEN+1),
    parameter BANK_COUNT_WIDTH=(BANKS<=1)?1:$clog2(BANKS+1)
)(
    input logic clk,rst_n,finish_write_bank,write_bank_blocked,
    input logic coalesce_enable,co_finish,output_fire,last_row_in_bank,
    input logic [BANK_WIDTH-1:0] write_bank,read_bank,co_current_bank,
    input logic [COUNT_WIDTH-1:0] write_rows_next,
    input logic [BANK_COUNT_WIDTH-1:0] co_tiles,
    output wire o_read_bank_ready,
    output wire [COUNT_WIDTH-1:0] o_read_bank_count,o_co_bank_count,
    output wire [BANKS-1:0] o_bank_ready,o_raw_nonempty
);
    localparam bit p_count_storage=BANKS>=8 && (BANKS & (BANKS-1))==0;
    logic [BANKS-1:0] bank_ready,bank_write_complete,bank_release;
    
{declarations}
{selection}
{storage}
{qualification}
{state}
    assign o_read_bank_ready=read_bank_ready;
    assign o_read_bank_count=read_bank_count;
    assign o_co_bank_count=co_bank_count;
    assign o_bank_ready=bank_ready;
    for(genvar bank=0;bank<BANKS;bank++) begin:g_observe
        if(p_count_storage) assign o_raw_nonempty[bank]={raw_nonempty};
        else assign o_raw_nonempty[bank]=1'b0;
    end
endmodule
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--reference", default="cedf4ed33661a53c8194eca1d484cdc2279d7549")
    parser.add_argument("--reference-file", type=Path)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_path = args.source_root / SOURCE
    source = source_path.read_text()
    reference = (args.reference_file.read_text() if args.reference_file else
                 read_rtl_source(f"{args.reference}:{SOURCE}", cwd=ROOT, text=True))
    models = []
    for label, text in (("reference", reference), ("current", source)):
        path = out / f"{label}.sv"
        path.write_text(model(text, label))
        models.append(path)
    profiles = [(16,1),(16,2),(16,3),(16,8),(16,16),(16,32),(16,64),(8,8),(32,32)]
    bench = """module count_pair #(parameter VLEN=16,BANKS=32)(
    input logic clk,rst_n,input logic [7:0] controls,
    input logic [31:0] values,output wire o_equal
);
    localparam BW=(BANKS<=1)?1:$clog2(BANKS), CW=$clog2(VLEN+1);
    localparam BCW=(BANKS<=1)?1:$clog2(BANKS+1);
    wire ready[2];
    wire [CW-1:0] read_count[2],co_count[2];
    wire [BANKS-1:0] valid[2],nonempty[2];
"""
    controls = ["finish_write_bank", "write_bank_blocked", "coalesce_enable", "co_finish",
                "output_fire", "last_row_in_bank"]
    for index, label in enumerate(("reference", "current")):
        names = ",".join(f".{name}(controls[{bit}])" for bit, name in enumerate(controls))
        bench += f"""
    {label}_count #(.VLEN(VLEN),.BANKS(BANKS)) u_{label}(
        .clk,.rst_n,{names},.write_bank(values[0+:BW]),.read_bank(values[6+:BW]),
        .co_current_bank(values[12+:BW]),.write_rows_next(values[18+:CW]),
        .co_tiles(values[24+:BCW]),.o_read_bank_ready(ready[{index}]),
        .o_read_bank_count(read_count[{index}]),.o_co_bank_count(co_count[{index}]),
        .o_bank_ready(valid[{index}]),.o_raw_nonempty(nonempty[{index}]));
"""
    bench += """
    assign o_equal=(ready[0]===ready[1]) && (read_count[0]===read_count[1]) &&
        (co_count[0]===co_count[1]) && (valid[0]===valid[1]) && (nonempty[0]===nonempty[1]);
endmodule
module tb;
    logic clk=0,rst_n=0;
    logic [7:0] controls=0;
    logic [31:0] values=0,random_state=32'h63a4ec19;
    integer cycle,bit_index;
    function automatic logic symbol(input logic [3:0] value);
        case(value)
            4'd0:symbol=1'bx;
            4'd1:symbol=1'bz;
            default:symbol=value[0];
        endcase
    endfunction
    task automatic advance_random;
        random_state=random_state^(random_state<<13);
        random_state=random_state^(random_state>>17);
        random_state=random_state^(random_state<<5);
    endtask
"""
    for index, (vlen, banks) in enumerate(profiles):
        bench += f"""
    wire equal_{index};
    count_pair #(.VLEN({vlen}),.BANKS({banks})) u_pair_{index}(
        .clk,.rst_n,.controls,.values,.o_equal(equal_{index}));
    always @(negedge clk) begin
        if(equal_{index}!==1'b1)
            $fatal(1,"FIFO count mismatch profile={index} cycle=%0d",cycle);
    end
"""
    bench += """
    initial begin
        #1;clk=1;#1;clk=0;#1;
        for(cycle=0;cycle<24000;cycle=cycle+1) begin
            advance_random();
            rst_n=(cycle%257==0)?1'b0:((cycle%31==0)?symbol(random_state[3:0]):1'b1);
            for(bit_index=0;bit_index<8;bit_index=bit_index+1) begin
                advance_random();controls[bit_index]=symbol(random_state[3:0]);
            end
            for(bit_index=0;bit_index<32;bit_index=bit_index+1) begin
                advance_random();values[bit_index]=symbol(random_state[3:0]);
            end
            if(cycle%16<8) begin
                controls=8'b00000001;
                values[0+:6]=6'(cycle);
                values[6+:6]=6'(cycle-1);
                values[12+:6]=6'(cycle);
                if(cycle%16==0) values[18+:6]='0;
                if(cycle%16==1) values[18+:6]=6'b00000x;
                if(cycle%16==2) values[18+:6]=6'b10000x;
                if(cycle%16==3) rst_n=1'bx;
                if(cycle%16==4) rst_n=1'bz;
            end
            #1;clk=1;#1;clk=0;#1;
        end
        $display("FIFO_READ_QUALIFICATION_FOUR_STATE_PASS cycles=24000 profiles=9 comparisons=1080000");
        $finish;
    end
endmodule
"""
    testbench = out / "tb.sv"
    testbench.write_text(bench)
    binary = out / "simulation"
    regfile = ROOT / "rtl/common/regfile.v"
    with (out / "compile.log").open("w") as stream:
        subprocess.run([args.iverilog, "-g2012", "-s", "tb", "-o", str(binary),
                        *map(str, models), str(regfile), str(testbench)],
                       stdout=stream, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run([args.vvp, str(binary)], capture_output=True, text=True, timeout=300)
    (out / "run.log").write_text(result.stdout + result.stderr)
    result.check_returncode()
    if "FIFO_READ_QUALIFICATION_FOUR_STATE_PASS" not in result.stdout:
        raise RuntimeError("四态比较未完成")
    if source != source_path.read_text():
        raise RuntimeError("验证期间源码发生变化")
    report = dict(passed=True, cycles=24000, profiles=profiles, comparisons=1080000,
                  source_sha256=digest(source_path), reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  regfile_sha256=digest(regfile), testbench_sha256=digest(testbench),
                  model_sha256={p.name:digest(p) for p in models}, log_sha256=digest(out / "run.log"))
    (out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(result.stdout, end="")


if __name__ == "__main__":
    main()
