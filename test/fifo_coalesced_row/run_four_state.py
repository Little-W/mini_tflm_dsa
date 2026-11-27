#!/usr/bin/env python3
"""逐周期比较并行行结束选择与完整行数数组的四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[2]
MODES={
 'generic':'`undef SYNTHESIS\n`undef XILINX_FPGA\n',
 'synthesis':'`define SYNTHESIS 1\n`undef XILINX_FPGA\n',
 'fpga':'`undef SYNTHESIS\n`define XILINX_FPGA 1\n',
 'fpga_synthesis':'`define SYNTHESIS 1\n`define XILINX_FPGA 1\n'}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/writeback'/name for name in ('vec_s8_fifo_row_match.sv','vec_s8_fifo_group_end.sv')]
    hashes={str(p):digest(p) for p in sources};runs=[]
    include=''.join(f'`include "{p}"\n' for p in sources)
    for mode,definitions in MODES.items():
      for banks,width in ((8,4),(8,5),(16,5),(32,5),(64,5),(8,7)):
        label=f'{mode}_n{banks}_w{width}';bench=out/(label+'.sv')
        bench.write_text(definitions+include+f'''
// 比较相同写入事件和任意有效位下的完整计数、行结束及组结束四态结果。
module tb;
  localparam integer B={banks};
  localparam integer W={width};
  localparam integer A=$clog2(B);
  logic clk=0;
  logic write_enable;
  logic [A-1:0] write_bank,read_bank;
  logic [W-1:0] write_count,row_limit;
  logic [B-1:0] bank_ready;
  logic [W-1:0] reference_count[B];
  wire row_last,group_last;
  logic row_boundary,transpose_mode,transpose_row_last,tile_row_last;
  logic expected_row,expected_group;
  integer checks=0;
  integer seed=32'h51a96ec7;
  vec_s8_fifo_row_match #(.p_banks(B),.p_count_width(W),.p_bank_width(A)) dut(
    .i_clk(clk),.i_write_enable(write_enable),.i_write_bank(write_bank),
    .i_write_count(write_count),.i_bank_ready(bank_ready),.i_row_limit(row_limit),
    .i_read_bank(read_bank),.o_row_last(row_last));
  vec_s8_fifo_group_end group_end(
    .i_row_boundary(row_boundary),.i_transpose(transpose_mode),
    .i_transpose_row_last(transpose_row_last),.i_tile_row_last(tile_row_last),
    .i_bank_row_last(row_last),.o_group_last(group_last));
  always @(posedge clk) begin
    if(write_enable) reference_count[write_bank] <= write_count;
  end
  function automatic logic value4(input integer code);
    case(code & 3)
      0:value4=1'b0;
      1:value4=1'b1;
      2:value4=1'bx;
      3:value4=1'bz;
    endcase
  endfunction
  task automatic compare;
    #1;
    expected_row=row_limit >= (bank_ready[read_bank] ? reference_count[read_bank] : '0);
    expected_group=row_boundary && (transpose_mode ? transpose_row_last : (tile_row_last && expected_row));
    if(row_last !== expected_row || group_last !== expected_group)
      $fatal(1,"row predicate checks=%0d actual=%b expected=%b bank=%b",checks,row_last,expected_row,read_bank);
    for(integer bank=0;bank<B;bank++) begin
      if(dut.count_q[bank] !== reference_count[bank])
        $fatal(1,"saved count checks=%0d bank=%0d",checks,bank);
    end
    checks++;
  endtask
  task automatic tick;
    compare();#3;clk=1;compare();#3;clk=0;
  endtask
  initial begin
    write_enable=0;write_bank=0;write_count=0;read_bank=0;row_limit=0;bank_ready=0;
    row_boundary=1;transpose_mode=0;transpose_row_last=1;tile_row_last=1;tick();
    for(integer bank=0;bank<B;bank++) begin
      write_enable=1;write_bank=A'(bank);read_bank=A'(bank);write_count=W'(bank+1);tick();
    end
    bank_ready='1;write_enable=0;
    for(integer bank=0;bank<B;bank++) begin
      read_bank=A'(bank);
      for(integer limit=0;limit<(1<<W);limit++) begin
        row_limit=W'(limit);tick();
      end
    end
    for(integer trial=0;trial<32768;trial++) begin
      write_enable=value4(trial);write_bank=$random(seed);read_bank=$random(seed);
      write_count=$random(seed);row_limit=$random(seed);
      for(integer bank=0;bank<B;bank++) bank_ready[bank]=trial[bank%15];
      row_boundary=value4(trial>>2);transpose_mode=value4(trial>>4);
      transpose_row_last=value4(trial>>6);tile_row_last=value4(trial>>8);
      case(trial%12)
        0:begin end
        1:read_bank[trial%A]=1'bx;
        2:read_bank[trial%A]=1'bz;
        3:begin write_enable=1;write_bank[trial%A]=1'bx;end
        4:begin write_enable=1;write_bank[trial%A]=1'bz;end
        5:begin write_enable=1;write_count[trial%W]=1'bx;end
        6:begin write_enable=1;write_count[trial%W]=1'bz;end
        7:bank_ready[read_bank]=1'bx;
        8:bank_ready[read_bank]=1'bz;
        9:row_limit[trial%W]=value4(trial>>9);
        10:begin
          for(integer bank=0;bank<B;bank++) bank_ready[bank]=value4($random(seed));
        end
        11:begin
          for(integer bit_index=0;bit_index<W;bit_index++) begin
            row_limit[bit_index]=value4($random(seed));
            write_count[bit_index]=value4($random(seed));
          end
        end
      endcase
      tick();
    end
    $display("FIFO_ROW_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
''')
        binary=out/(label+'.vvp')
        build=subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb','-o',str(binary),str(bench)],
                             stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=120)
        (out/(label+'_build.log')).write_text(build.stdout)
        result=subprocess.run([shutil.which('vvp') or 'vvp',str(binary)],stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT,text=True,check=True,timeout=180)
        log=out/(label+'.log');log.write_text(result.stdout)
        match=re.search(r'FIFO_ROW_FOUR_STATE_PASS checks=(\d+)',result.stdout);assert match
        row=dict(mode=mode,banks=banks,count_width=width,checks=int(match[1]),passed=True,log_sha256=digest(log))
        runs.append(row);print(json.dumps(row),flush=True)
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        runner_sha256=digest(__file__),runs=runs,comparisons=sum(x['checks'] for x in runs)),indent=2)+'\n')


if __name__=='__main__':
    main()
