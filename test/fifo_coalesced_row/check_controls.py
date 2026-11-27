#!/usr/bin/env python3
"""枚举组结束与读取使能组合条件的全部四态输入。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from run_four_state import ROOT,MODES,digest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    sources=[ROOT/'rtl/npu/writeback'/name for name in ('vec_s8_fifo_group_end.sv','vec_s8_fifo_read_enable.sv')]
    hashes={str(p):digest(p) for p in sources};runs=[]
    includes=''.join(f'`include "{p}"\n' for p in sources)
    for mode,definitions in MODES.items():
        bench=out/(mode+'.sv')
        bench.write_text(definitions+includes+'''
// 对五输入组结束和九输入读取使能执行完整四态组合检查。
module tb;
  logic [8:0] control;
  wire group_last,read_enable;
  logic expected_group,expected_read;
  integer checks=0;
  vec_s8_fifo_group_end group_end(
    .i_row_boundary(control[4]),.i_transpose(control[3]),
    .i_transpose_row_last(control[2]),.i_tile_row_last(control[1]),
    .i_bank_row_last(control[0]),.o_group_last(group_last));
  vec_s8_fifo_read_enable reader(
    .i_coalesce(control[8]),.i_group_start(control[7]),.i_waiting_ready(control[6]),
    .i_group_fire(control[5]),.i_group_last(control[4]),.i_next_bank_ready(control[3]),
    .i_stream_start(control[2]),.i_stream_next(control[1]),.i_refresh_first(control[0]),
    .o_read_enable(read_enable));
  function automatic logic value4(input integer code);
    case(code & 3)
      0:value4=1'b0;
      1:value4=1'b1;
      2:value4=1'bx;
      3:value4=1'bz;
    endcase
  endfunction
  initial begin
    for(integer pattern=0;pattern<262144;pattern++) begin
      for(integer bit_index=0;bit_index<9;bit_index++) control[bit_index]=value4(pattern>>(2*bit_index));
      #1;
      expected_group=control[4] && (control[3] ? control[2] : (control[1] && control[0]));
      expected_read=control[8] ? (control[7] || control[6] || (control[5] && !control[4] && control[3])) :
          (control[2] || control[1] || control[0]);
      if(group_last !== expected_group || read_enable !== expected_read)
        $fatal(1,"FIFO control combination=%0d",pattern);
      checks++;
    end
    $display("FIFO_CONTROLS_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
''')
        binary=out/(mode+'.vvp')
        build=subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb','-o',str(binary),str(bench)],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True,timeout=120)
        (out/(mode+'_build.log')).write_text(build.stdout)
        result=subprocess.run([shutil.which('vvp') or 'vvp',str(binary)],stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,check=True,timeout=120)
        log=out/(mode+'.log');log.write_text(result.stdout)
        match=re.search(r'FIFO_CONTROLS_FOUR_STATE_PASS checks=(\d+)',result.stdout);assert match
        row=dict(mode=mode,checks=int(match[1]),passed=True,log_sha256=digest(log))
        runs.append(row);print(json.dumps(row),flush=True)
    assert all(digest(p)==h for p,h in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        runner_sha256=digest(__file__),runs=runs,comparisons=sum(x['checks'] for x in runs)),indent=2)+'\n')


if __name__=='__main__':
    main()
