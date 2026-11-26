#!/usr/bin/env python3
"""在真实共享数组中检查 IA 写排列、掩码、并发访问与四态返回保持。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

from run_formal import ROOT, REFERENCE, CACHE, digest, original
from run_closed import CHANNEL, execute
sys.path.insert(0, str(ROOT))
from scripts.rtl.source_files import input_files, with_dependencies


def stage(source, variant):
    begin = source.index("    always_ff @(posedge clk) begin", source.index("    // 写命令"))
    end = source.index("    wire [RAM_WORD_ADDR_WIDTH-1:0] write_row_word", begin)
    selected = source[begin:end]
    begin = source.index("    if (SIZE == 16 && DATA_WIDTH == 16) begin : g_write_port_range")
    end = source.index("    for (genvar lane = 0; lane < SIZE; lane++) begin : g_write_lane", begin)
    selected += source[begin:end]
    return f"""// 直接采用实际写命令寄存级和端口范围判定。
module write_stage_{variant} #(parameter integer DMA_LANES=8,COMPACT_S8=0)(
 input wire logic clk,rst_n,compact_mode,
 input wire logic signed [15:0] compact_offset,
 input wire logic [4:0] wr_slot,
 input wire logic [3:0] wr_row,wr_col_base,
 input wire logic signed [15:0] wr_data[DMA_LANES],
 input wire logic wr_valid[DMA_LANES],
 output logic [1:0] ram_port_wr_en,
 output logic [11:0] ram_port_wr_addr[0:1],
 output logic [127:0] ram_port_wr_data[0:1],ram_shared_wr_data,
 output logic [15:0] ram_port_wr_mask[0:1]);
 localparam integer SIZE=16,DATA_WIDTH=16,RAM_WORD_ADDR_WIDTH=12,LOG2_SIZE=4;
 localparam p_shared_write_stage=1'b1,p_zero_masked_write_data=1'b0;
 wire compact_active=(COMPACT_S8!=0) && compact_mode;
 wire [7:0] compact_empty_byte=8'(0-compact_offset);
 logic [1:0] write_en;
 wire [11:0] write_addr[0:1];
 logic [127:0] write_data[0:1];
 logic [15:0] write_mask[0:1];
 wire [11:0] write_row_word=12'({{wr_slot,wr_row}}) << (compact_active ? 0 : 1);
 assign write_addr[0]=write_row_word;
 assign write_addr[1]=write_row_word+12'(1);
{selected}
endmodule
"""


BENCH = r'''
module comparison #(parameter integer COMPACT=0,LANES=8)(
 input wire logic clk,rst_n,input integer sample);
 logic compact_mode;
 logic signed [15:0] compact_offset;
 logic [4:0] wr_slot;
 logic [3:0] wr_row,wr_col_base;
 logic signed [15:0] wr_data[LANES];
 logic wr_valid[LANES];
 wire [1:0] reference_enable,current_enable;
 wire [11:0] reference_address[2],current_address[2];
 wire [127:0] reference_words[2],current_words[2],reference_shared,current_shared;
 wire [15:0] reference_mask[2],current_mask[2];
 wire [1:0] reference_ram_enable,current_ram_enable;
 wire [15:0] reference_ram_mask[2],current_ram_mask[2];
 logic force_zero_write;
 logic access_enable,configure;
 logic [2:0] ia_banks;
 logic [1:0] ia_read_enable;
 logic [11:0] ia_read_address[2],ps_read_address[4],ps_write_address[4];
 logic [3:0] ps_read_enable,ps_write_enable;
 logic [127:0] ps_write_data[4];
 wire [127:0] reference_ia[2],current_ia[2],reference_ps[4],current_ps[4];
 wire reference_fault,current_fault;
 integer writes=0,reads=0,partial_masks=0,zero_masks=0,cross_half=0;
 integer port_zero=0,port_one=0,overlaps=0,same_address=0,invalid=0,unknowns=0;
 integer physical_ia_writes=0,zero_requests=0;
 integer memory_checks=0,return_checks=0,byte_checks=0;
 logic [31:0] random_state=32'h3194a5cb+COMPACT*17+LANES;
 function automatic [31:0] random_word();
  random_state=random_state^(random_state<<13);
  random_state=random_state^(random_state>>17);
  random_state=random_state^(random_state<<5);
  random_word=random_state;
 endfunction
 assign reference_ram_enable=force_zero_write ? 2'b01 : reference_enable;
 assign current_ram_enable=force_zero_write ? 2'b01 : current_enable;
 for(genvar port_index=0;port_index<2;port_index++)begin:g_zero_request
  assign reference_ram_mask[port_index]=force_zero_write ? 16'd0 : reference_mask[port_index];
  assign current_ram_mask[port_index]=force_zero_write ? 16'd0 : current_mask[port_index];
 end
 write_stage_reference #(.DMA_LANES(LANES),.COMPACT_S8(COMPACT)) u_reference_stage (
 .clk(clk),.rst_n(rst_n),.compact_mode(compact_mode),.compact_offset(compact_offset),
 .wr_slot(wr_slot),.wr_row(wr_row),.wr_col_base(wr_col_base),.wr_data(wr_data),.wr_valid(wr_valid),
 .ram_port_wr_en(reference_enable),.ram_port_wr_addr(reference_address),
 .ram_port_wr_data(reference_words),.ram_shared_wr_data(reference_shared),.ram_port_wr_mask(reference_mask));
 write_stage_candidate #(.DMA_LANES(LANES),.COMPACT_S8(COMPACT)) u_candidate_stage (
 .clk(clk),.rst_n(rst_n),.compact_mode(compact_mode),.compact_offset(compact_offset),
 .wr_slot(wr_slot),.wr_row(wr_row),.wr_col_base(wr_col_base),.wr_data(wr_data),.wr_valid(wr_valid),
 .ram_port_wr_en(current_enable),.ram_port_wr_addr(current_address),
 .ram_port_wr_data(current_words),.ram_shared_wr_data(current_shared),.ram_port_wr_mask(current_mask));
 ia_ps_channel_ram #(.p_shared_write_stage(1),.p_ia_nonempty_writes(1),.p_paired_ia_ports(1),
 .p_allow_inactive_return_updates(1),.p_bank_bytes(8192),.p_total_bytes(57344)) u_reference (
 .clk(clk),.rst_n(rst_n),.i_access_enable(access_enable),.i_cfg_valid(configure),.i_cfg_ia_banks(ia_banks),
 .o_capacity_fault(reference_fault),.i_ia_read_en(ia_read_enable),.i_ia_write_en(reference_ram_enable),
 .i_ia_read_addr(ia_read_address),.i_ia_write_addr(reference_address),.o_ia_read_data(reference_ia),
 .i_ia_write_data(reference_words),.i_ia_shared_write_data(reference_shared),.i_ia_write_mask(reference_ram_mask),
 .i_ps_read_en(ps_read_enable),.i_ps_write_en(ps_write_enable),.i_ps_read_addr(ps_read_address),
 .i_ps_write_addr(ps_write_address),.o_ps_read_data(reference_ps),.i_ps_write_data(ps_write_data));
 ia_ps_channel_ram #(.p_shared_write_stage(1),.p_ia_nonempty_writes(1),.p_paired_ia_ports(1),
 .p_allow_inactive_return_updates(1),.p_bank_bytes(8192),.p_total_bytes(57344)) u_candidate (
 .clk(clk),.rst_n(rst_n),.i_access_enable(access_enable),.i_cfg_valid(configure),.i_cfg_ia_banks(ia_banks),
 .o_capacity_fault(current_fault),.i_ia_read_en(ia_read_enable),.i_ia_write_en(current_ram_enable),
 .i_ia_read_addr(ia_read_address),.i_ia_write_addr(current_address),.o_ia_read_data(current_ia),
 .i_ia_write_data(current_words),.i_ia_shared_write_data(current_shared),.i_ia_write_mask(current_ram_mask),
 .i_ps_read_en(ps_read_enable),.i_ps_write_en(ps_write_enable),.i_ps_read_addr(ps_read_address),
 .i_ps_write_addr(ps_write_address),.o_ps_read_data(current_ps),.i_ps_write_data(ps_write_data));

 always @(negedge clk) begin
  compact_mode=COMPACT && sample[8];
  compact_offset=16'(random_word());
  wr_slot=5'(sample>>4);wr_row=4'(sample);wr_col_base=4'((sample>>1)+(sample>>7));
  for(integer lane=0;lane<LANES;lane++)begin
   // 两种输入格式覆盖符号扩展字节和任意完整半字。
   wr_data[lane]=sample[0] ? 16'(random_word()) : 16'($signed(8'(random_word())));
   wr_valid[lane]=(sample%128>=4) && (sample%17!=0) && (sample%5==0 || 1'(random_word()));
  end
  access_enable=(sample%31!=0);
  force_zero_write=(sample%128>=4 && sample%41==20);
  configure=(sample<4 || sample%128==2);
  ia_banks=sample[10] ? 3'd1 : 3'd2;
  ia_read_enable=(sample%128>=4 && (sample%3==0 || sample%31==15)) ? (ia_banks==2 ? 2'b11 : 2'b01) : 2'b00;
  ia_read_address[0]=sample%31==15 ? reference_address[0] :
      (ia_banks==2 ? 12'(2*((sample+131)%512)) : 12'((sample+131)%512));
  ia_read_address[1]=sample%31==15 ? reference_address[1] : ia_read_address[0]+12'(1);
  ps_read_enable=(sample%128>=4 && sample%11==0) ? 4'b1111 : 4'b0000;
  ps_write_enable=(sample%128>=4 && sample%13==0) ? 4'b1111 : 4'b0000;
  for(integer channel=0;channel<4;channel++)begin
   ps_read_address[channel]=12'(sample%640);
   ps_write_address[channel]=sample%19==0 ? ps_read_address[channel] : 12'((sample+7)%640);
   ps_write_data[channel]={random_word(),random_word(),random_word(),random_word()};
  end
  if(sample%17==0)zero_masks++;
  if(sample>2048)begin
   case(sample%127)
    0:begin wr_valid[sample%LANES]=1'bx;unknowns++;end
    1:begin wr_col_base[1]=1'bz;unknowns++;end
    2:begin compact_mode=1'bx;unknowns++;end
    3:begin access_enable=1'bx;unknowns++;end
    4:begin wr_data[sample%LANES][7:0]='x;unknowns++;end
    5:begin wr_data[sample%LANES][15:8]='z;unknowns++;end
    6:begin ia_read_enable[0]=1'bx;unknowns++;end
    7:begin ps_write_enable[1]=1'bz;unknowns++;end
    8:begin configure=1'bx;unknowns++;end
    9:begin ia_banks=3'd3;configure=1'b1;invalid++;end
    10:begin ia_read_address[0]='1;ia_read_enable[0]=1'b1;invalid++;end
    11:begin ps_write_address[0]='1;ps_write_enable[0]=1'b1;invalid++;end
    12:begin wr_slot[2]=1'bx;unknowns++;end
    default:begin end
   endcase
  end
 end
 always @(posedge clk)begin
  if(force_zero_write===1'b1)zero_requests++;
  if(u_candidate.u_ia_ram.i_wr_en===1'b1 && (|u_candidate.u_ia_ram.i_wr_mask)===1'b1)
   physical_ia_writes++;
  for(integer port_index=0;port_index<2;port_index++)begin
   if(reference_ram_enable[port_index]===1'b1 && ia_read_enable[port_index]===1'b1)begin
    overlaps++;
    if(reference_address[port_index]==ia_read_address[port_index])same_address++;
   end
  end
  #1;
  if(reference_enable!==current_enable || reference_fault!==current_fault)
   $fatal(1,"Control differs compact=%0d lanes=%0d sample=%0d",COMPACT,LANES,sample);
  for(integer port_index=0;port_index<2;port_index++)begin
   if(reference_address[port_index]!==current_address[port_index] ||
      reference_mask[port_index]!==current_mask[port_index] ||
      reference_ia[port_index]!==current_ia[port_index])
     $fatal(1,"IA interface differs compact=%0d lanes=%0d sample=%0d port=%0d",COMPACT,LANES,sample,port_index);
   return_checks++;
   if(reference_enable[port_index]===1'b1)writes++;
   if(ia_read_enable[port_index]===1'b1)reads++;
   if(reference_mask[port_index]!=0 && reference_mask[port_index]!=16'hffff)partial_masks++;
   for(integer byte_index=0;byte_index<16;byte_index++)begin
    if(reference_mask[port_index][byte_index]===1'b1)begin
     if(reference_words[port_index][8*byte_index+:8]!==current_words[port_index][8*byte_index+:8])
      $fatal(1,"Enabled byte differs sample=%0d",sample);
     byte_checks++;
    end
   end
  end
  if(reference_enable[1]===1'b1)port_one++;else if(reference_enable[0]===1'b1)port_zero++;
  if(reference_enable===2'b11 && wr_col_base[2:0]!=0)cross_half++;
  for(integer channel=0;channel<4;channel++)begin
   if(reference_ps[channel]!==current_ps[channel])$fatal(1,"PS return differs sample=%0d",sample);
   return_checks++;
  end
  for(integer row=0;row<512;row++)begin
   if(u_reference.u_ia_ram.mem[row]!==u_candidate.u_ia_ram.mem[row])
    $fatal(1,"IA memory differs compact=%0d lanes=%0d sample=%0d row=%0d",COMPACT,LANES,sample,row);
   memory_checks++;
  end
 end
 for(genvar channel=0;channel<4;channel++)begin:g_memory_compare
  integer physical_writes=0;
  always @(posedge clk)begin
`ifdef XILINX_FPGA
   if(u_candidate.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.i_access_enable===1'b1 &&
      ((u_candidate.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.i_a_write===1'b1 &&
        (|u_candidate.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.i_a_mask)===1'b1) ||
       u_candidate.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.i_b_write===1'b1))physical_writes++;
`else
   if(u_candidate.g_shared_bank[1].g_channel[channel].g_held_response.u_ram.i_wr_en===1'b1 &&
      (|u_candidate.g_shared_bank[1].g_channel[channel].g_held_response.u_ram.i_wr_mask)===1'b1)physical_writes++;
`endif
   #1;
   for(integer row=0;row<640;row++)
    if(u_reference.g_fixed_channel[channel].u_ram.mem[row]!==u_candidate.g_fixed_channel[channel].u_ram.mem[row])
      $fatal(1,"Fixed PS memory differs sample=%0d channel=%0d row=%0d",sample,channel,row);
   for(integer row=0;row<128;row++)begin
`ifdef XILINX_FPGA
    if(u_reference.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.memory[row]!==
       u_candidate.g_shared_bank[1].g_channel[channel].g_qualified_response.u_ram.memory[row])
`else
    if(u_reference.g_shared_bank[1].g_channel[channel].g_held_response.u_ram.mem[row]!==
       u_candidate.g_shared_bank[1].g_channel[channel].g_held_response.u_ram.mem[row])
`endif
       $fatal(1,"Shared memory differs sample=%0d channel=%0d row=%0d",sample,channel,row);
   end
  end
 end
 task report;
  if(writes<500 || reads<500 || partial_masks<500 || zero_masks<100 || cross_half<100 ||
     port_zero<100 || port_one<100 || overlaps<100 || same_address<20 || invalid<30 || unknowns<100 ||
     physical_ia_writes<100 || zero_requests<100)begin
    $display("COVERAGE writes=%0d reads=%0d partial=%0d zero=%0d cross=%0d port0=%0d port1=%0d overlaps=%0d same=%0d invalid=%0d unknown=%0d physical=%0d",
      writes,reads,partial_masks,zero_masks,cross_half,port_zero,port_one,overlaps,same_address,invalid,unknowns,physical_ia_writes);
    $fatal(1,"Insufficient coverage compact=%0d lanes=%0d",COMPACT,LANES);
  end
  $display("IA_MASKED_MEMORY_PASS compact=%0d lanes=%0d writes=%0d reads=%0d partial=%0d zero=%0d cross_half=%0d port_zero=%0d port_one=%0d overlaps=%0d same_address=%0d invalid=%0d unknowns=%0d return_checks=%0d byte_checks=%0d memory_checks=%0d physical_ia_writes=%0d physical_shared_writes=%0d zero_requests=%0d",
     COMPACT,LANES,writes,reads,partial_masks,zero_masks,cross_half,port_zero,port_one,overlaps,same_address,invalid,unknowns,return_checks,byte_checks,7*memory_checks,physical_ia_writes,
     g_memory_compare[0].physical_writes+g_memory_compare[1].physical_writes+
     g_memory_compare[2].physical_writes+g_memory_compare[3].physical_writes,zero_requests);
 endtask
endmodule
module tb;
 logic clk=1,rst_n=0;
 integer sample=0;
 comparison #(.COMPACT(0),.LANES(8)) u_regular(clk,rst_n,sample);
 comparison #(.COMPACT(1),.LANES(8)) u_compact(clk,rst_n,sample);
 comparison #(.COMPACT(1),.LANES(4)) u_four_lanes(clk,rst_n,sample);
 initial begin
  for(sample=0;sample<CYCLES;sample++)begin
   rst_n=sample>2 && sample%2053!=0;
   #2;clk=0;#2;clk=1;#2;
  end
  u_regular.report();u_compact.report();u_four_lanes.report();
  $display("IA_MASKED_MEMORY_ALL_PASS");$finish;
 end
endmodule
'''


def compatible(text):
    text = text.replace("int unsigned", "integer").replace("always_comb", "always @*")
    text = re.sub(r"(input\s+(?:wire\s+)?logic\s+(?:i_access_enable|i_a_read_allowed))\s*=\s*1'b1", r"\1", text)
    return text.replace(" = 128'd0 /* 预先选择的共享物理存储块写数据 */", " /* 预先选择的共享物理存储块写数据 */")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reference", default=REFERENCE)
    parser.add_argument("--cycles", type=int, default=8192)
    parser.add_argument("--modes", nargs="+", choices=("generic", "fpga"), default=("generic", "fpga"))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current, reference = (ROOT / CACHE).read_text(), original(CACHE, args.reference)
    dependencies = with_dependencies([ROOT / CHANNEL], ROOT)
    hashes = {str(path.relative_to(ROOT)): digest(path)
              for path in input_files([ROOT / CACHE, *dependencies], ROOT)}
    generated = []
    for path in dependencies:
        if not path.is_file():
            continue
        destination = out / "sources" / path.name
        destination.parent.mkdir(exist_ok=True)
        destination.write_text(compatible(path.read_text()))
        generated.append(destination)
    design = out / "tb.sv"
    design.write_text(compatible(stage(reference, "reference") + stage(current, "candidate") +
                                BENCH.replace("CYCLES", str(args.cycles))))
    records = []
    for mode in args.modes:
        flags = ["-DSYNTHESIS=1", "-DXILINX_FPGA=1"] if mode == "fpga" else []
        binary, log = out / (mode + ".vvp"), out / (mode + ".log")
        execute(["iverilog", "-g2012", "-s", "tb", *flags, "-o", binary, design, *generated],
                out / (mode + "_compile.log"))
        result = execute(["vvp", binary], log, timeout=600)
        lines = [line for line in result.splitlines() if line.startswith("IA_MASKED_MEMORY_PASS")]
        if len(lines) != 3 or "IA_MASKED_MEMORY_ALL_PASS" not in result:
            raise RuntimeError("实际共享数组检查未完成：" + mode)
        profiles = [{name: int(value) for name, value in re.findall(r"(\w+)=(\d+)", line)} for line in lines]
        record = dict(mode=mode, passed=True, cycles_per_profile=args.cycles, profiles=profiles,
                      all_memory_words_compared=True, all_return_cycles_compared=True,
                      testbench_sha256=digest(design), log_sha256=digest(log))
        records.append(record)
        print(json.dumps(record), flush=True)
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise RuntimeError("四态存储检查期间源码发生变化")
    (out / "summary.json").write_text(json.dumps(dict(passed=True, reference=args.reference,
        source_sha256=hashes, runner_sha256=digest(__file__), runs=records), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
