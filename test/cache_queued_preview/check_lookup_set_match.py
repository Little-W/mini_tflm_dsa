#!/usr/bin/env python3
"""验证查询组号末级比较选择的任意输入等价及完整四态条件合并。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODES = {
    'generic':'`undef SYNTHESIS\n`undef XILINX_FPGA\n',
    'synthesis':'`define SYNTHESIS 1\n`undef XILINX_FPGA\n',
    'fpga':'`undef SYNTHESIS\n`define XILINX_FPGA 1\n',
    'fpga_synthesis':'`define SYNTHESIS 1\n`define XILINX_FPGA 1\n',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def instance(width):
    return f'''
  conv_cache_lookup_set_match #(.p_set_width({width})) dut(
    .i_bypass(bypass), .i_miss(miss), .i_fill_set(fill_set), .i_demand_set(demand_set),
    .i_work_set(work_set), .i_select_set(select_set), .o_match(match_result));
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'rtl/npu/dma/cache/conv_cache_lookup_set_match.sv'
    initial=digest(source);formal=[];four_state=[]
    for mode,definitions in MODES.items():
        for width in (1,2,4,5,8):
            label=f'{mode}_{width}'
            prefix=definitions+f'`include "{source}"\n'
            proof=out/(label+'_proof.sv')
            proof.write_text(prefix+f'''
module proof(input logic bypass,miss,
  input logic [{width-1}:0] fill_set,demand_set,work_set,select_set,
  output logic match_result);
'''+instance(width)+'''
  always_comb assert(match_result ==
      ((bypass ? fill_set : (miss ? demand_set : work_set)) == select_set));
endmodule
''')
            script=out/(label+'.ys')
            script.write_text(f'read_slang --top proof {proof}\n'
                'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top proof -flatten\nchformal -lower\n'
                'sat -verify -prove-asserts -show-inputs\n')
            log=out/(label+'_formal.log')
            with log.open('w') as stream:
                subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                    stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
            assert 'SUCCESS' in log.read_text()
            formal.append(dict(mode=mode,set_width=width,passed=True,input_constraints=[],log_sha256=digest(log)))
            bench=out/(label+'_tb.sv')
            bench.write_text(prefix+f'''
module tb;
  localparam integer W={width};
  logic bypass,miss;
  logic [W-1:0] fill_set,demand_set,work_set,select_set;
  wire match_result;
  logic expected;
  integer checks=0;
  integer seed=32'h593ba627;
'''+instance(width)+'''
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
    expected=(bypass ? fill_set : (miss ? demand_set : work_set)) == select_set;
    if(match_result !== expected)
      $fatal(1,"lookup set result checks=%0d bypass=%b miss=%b",checks,bypass,miss);
    checks++;
  endtask
  initial begin
    // 每一位均枚举三个候选、比较目标和两个控制的全部四态组合。
    for(integer control=0;control<16;control++) begin
      bypass=value4(control);miss=value4(control>>2);
      for(integer bit_index=0;bit_index<W;bit_index++) begin
        for(integer values=0;values<256;values++) begin
          fill_set='0;demand_set='0;work_set='0;select_set='0;
          fill_set[bit_index]=value4(values);
          demand_set[bit_index]=value4(values>>2);
          work_set[bit_index]=value4(values>>4);
          select_set[bit_index]=value4(values>>6);
          compare();
          // 另一位形成确定的不匹配，覆盖未知比较被确定结果吸收的情况。
          if(W>1) begin
            fill_set[(bit_index+1)%W]=1'b1;
            demand_set[(bit_index+1)%W]=1'b1;
            work_set[(bit_index+1)%W]=1'b1;
            compare();
          end
        end
      end
    end
    for(integer trial=0;trial<32768;trial++) begin
      bypass=value4(trial);miss=value4(trial>>2);
      fill_set=$random(seed);demand_set=$random(seed);work_set=$random(seed);
      case(trial%4)
        0:select_set=fill_set;
        1:select_set=demand_set;
        2:select_set=work_set;
        3:select_set=$random(seed);
      endcase
      case(trial%5)
        0: begin end
        1: fill_set[trial%W]=value4(trial>>4);
        2: begin demand_set[trial%W]=value4(trial>>4);work_set[(trial+1)%W]=value4(trial>>6);end
        3: select_set[trial%W]=value4(trial>>4);
        4: begin
          for(integer bit_index=0;bit_index<W;bit_index++) begin
            fill_set[bit_index]=value4($random(seed));
            demand_set[bit_index]=value4($random(seed));
            work_set[bit_index]=value4($random(seed));
            select_set[bit_index]=value4($random(seed));
          end
        end
      endcase
      compare();
    end
    $display("LOOKUP_SET_FOUR_STATE_PASS checks=%0d",checks);$finish;
  end
endmodule
''')
            binary=out/(label+'.vvp')
            build=subprocess.run([shutil.which('iverilog') or 'iverilog','-g2012','-s','tb',
                '-o',str(binary),str(bench)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,check=True,timeout=120)
            (out/(label+'_build.log')).write_text(build.stdout)
            run=subprocess.run([shutil.which('vvp') or 'vvp',str(binary)],stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,text=True,check=True,timeout=120)
            log=out/(label+'_four_state.log');log.write_text(run.stdout)
            checks=re.search(r'LOOKUP_SET_FOUR_STATE_PASS checks=(\d+)',run.stdout);assert checks
            four_state.append(dict(mode=mode,set_width=width,checks=int(checks[1]),passed=True,log_sha256=digest(log)))
            print(label,'PASS',checks[1],flush=True)
    assert digest(source)==initial
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256={str(source):initial},
        runner_sha256=digest(__file__),formal=formal,four_state=four_state,
        four_state_comparisons=sum(row['checks'] for row in four_state)),indent=2)+'\n')


if __name__=='__main__':
    main()
