#!/usr/bin/env python3
"""验证预读地址及并行组号比较的二态等价和四态结果。"""
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
PROFILES = ((1, 3), (2, 4), (4, 7), (5, 27), (8, 7))
MODES = {
    'generic': '`undef SYNTHESIS\n`undef XILINX_FPGA\n',
    'synthesis': '`define SYNTHESIS 1\n`undef XILINX_FPGA\n',
    'fpga': '`undef SYNTHESIS\n`define XILINX_FPGA 1\n',
    'fpga_synthesis': '`define SYNTHESIS 1\n`define XILINX_FPGA 1\n',
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declarations(width: int, shift: int) -> str:
    return f'''
  localparam integer W={width};
  localparam integer LB={shift};
  wire set_match;
  logic [W-1:0] selected_set;
  // 参考计算保留请求通路中的过程式 if 选择及完整移位宽度。
  always_comb begin
    if(windowed && index_valid) selected_set=W'(request_index);
    else selected_set=W'(request_address >> LB)^W'(request_address >> (LB+W));
  end
  conv_cache_preview_set_match #(.p_set_width(W),.p_line_shift(LB)) sets(
    .i_request_address(request_address), .i_request_index(request_index),
    .i_windowed(windowed), .i_index_valid(index_valid), .i_saved_set(saved_set),
    .o_match(set_match));
  conv_cache_queued_preview dut(
    .i_preview_selected(selected), .i_queue_empty(empty), .i_foreground_idle(idle),
    .i_request_address(request_address), .i_saved_address(saved_address),
    .i_set_match(set_match), .i_saved_range(range_value), .o_match(match_result));
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT/'rtl/npu/dma/cache'/name for name in (
        'conv_cache_preview_set_match.sv', 'conv_cache_queued_preview.sv')]
    hashes = {str(path):digest(path) for path in sources}
    includes = ''.join(f'`include "{path}"\n' for path in sources)
    formal, four_state = [], []
    for mode, definitions in MODES.items():
        for width, shift in PROFILES:
            label = f'{mode}_{width}_{shift}'
            proof = out/(label+'_proof.sv')
            proof.write_text(definitions+includes+f'''
module proof(input logic selected, empty, idle, range_value, windowed, index_valid,
             input logic [31:0] request_address, saved_address, request_index,
             input logic [{width-1}:0] saved_set, output logic match_result);
'''+declarations(width, shift)+'''
  always_comb begin
    assert(set_match == (selected_set == saved_set));
    assert(match_result == (selected && empty && idle &&
        request_address == saved_address && selected_set == saved_set));
  end
endmodule
''')
            script = out/(label+'.ys')
            script.write_text(f'read_slang --top proof {proof}\n'
                              'setattr -mod -unset keep_hierarchy\n'
                              'setattr -unset keep_hierarchy\nsetattr -unset keep\n'
                              'prep -top proof -flatten\nchformal -lower\n'
                              'sat -verify -prove-asserts -show-inputs\n')
            log = out/(label+'_formal.log')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
                                '--worker', script], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            assert 'SUCCESS' in log.read_text()
            formal.append(dict(mode=mode, set_width=width, line_shift=shift, passed=True,
                               input_constraints=[], log_sha256=digest(log)))
            bench = out/(label+'_tb.sv')
            bench.write_text(definitions+includes+f'''
module tb;
  reg selected, empty, idle, range_value, windowed, index_valid;
  reg [31:0] request_address, saved_address, request_index;
  reg [{width-1}:0] saved_set;
  wire match_result;
  reg expected;
  integer seed=32'h31c7ad95;
  integer checks=0;
'''+declarations(width, shift)+'''
  function automatic logic value4(input integer code);
    case(code & 3)
      0: value4=1'b0;
      1: value4=1'b1;
      2: value4=1'bx;
      3: value4=1'bz;
    endcase
  endfunction
  task automatic prepare;
    request_address=32'h36ac9e51;
    saved_address=request_address;
    request_index=32'hac734126;
    #1;
    saved_set=selected_set;
  endtask
  task automatic compare;
    #1;
    expected=1'b0;
    case ({selected,empty,idle,request_address==saved_address,selected_set==saved_set})
      5'b11111: expected=1'b1;
      default: begin end
    endcase
    case (range_value)
      1'b0,1'b1: begin end
      default: expected=1'b0;
    endcase
    if(set_match !== (selected_set==saved_set))
      $fatal(1,"set match result checks=%0d",checks);
    if(match_result !== expected)
      $fatal(1,"preview match result checks=%0d",checks);
    checks++;
  endtask
  initial begin
    // 六项控制的全部四态组合，每组均检查匹配及确定不匹配。
    for(integer control=0;control<4096;control++) begin
      selected=value4(control);empty=value4(control>>2);
      idle=value4(control>>4);range_value=value4(control>>6);
      windowed=value4(control>>8);index_valid=value4(control>>10);
      prepare();compare();
      saved_set=~saved_set;compare();
      saved_address=~request_address;compare();
    end
    selected=1;empty=1;idle=1;range_value=1;
    // 每一位地址、索引和保存组号均包含零、一、未知及高阻态。
    for(integer control=0;control<16;control++) begin
      windowed=value4(control);index_valid=value4(control>>2);
      for(integer bit_index=0;bit_index<32;bit_index++) begin
        for(integer code=0;code<4;code++) begin
          prepare();request_address[bit_index]=value4(code);compare();
          prepare();saved_address[bit_index]=value4(code);compare();
          prepare();request_index[bit_index]=value4(code);compare();
        end
      end
      for(integer bit_index=0;bit_index<W;bit_index++) begin
        for(integer code=0;code<4;code++) begin
          prepare();saved_set[bit_index]=value4(code);compare();
        end
      end
    end
    for(integer trial=0;trial<32768;trial++) begin
      request_address=$random(seed);saved_address=request_address;
      request_index=$random(seed);
      selected=1;empty=1;idle=1;range_value=trial[0];
      windowed=value4(trial>>1);index_valid=value4(trial>>3);
      #1;saved_set=selected_set;
      case(trial%12)
        0: begin end
        1: saved_address[trial%32]=~saved_address[trial%32];
        2: saved_address[trial%32]=1'bx;
        3: saved_address[trial%32]=1'bz;
        4: saved_set[trial%W]=value4(trial>>3);
        5: range_value=value4(trial>>3);
        6: begin selected=value4(trial>>3);empty=value4(trial>>5);idle=value4(trial>>7);end
        7: begin
          for(integer bit_index=0;bit_index<32;bit_index++) begin
            request_address[bit_index]=value4($random(seed));
            saved_address[bit_index]=value4($random(seed));
          end
        end
        8: request_index[trial%32]=value4(trial>>5);
        9: request_address[trial%32]=value4(trial>>5);
        10: begin
          for(integer bit_index=0;bit_index<W;bit_index++) begin
            request_index[bit_index]=value4($random(seed));
            saved_set[bit_index]=value4($random(seed));
          end
        end
        11: begin
          request_address[trial%32]=1'bx;
          request_address[(trial+1)%32]=1'bz;
          saved_set[trial%W]=1'bx;
        end
      endcase
      compare();
    end
    $display("QUEUED_PREVIEW_FOUR_STATE_PASS checks=%0d",checks);
    $finish;
  end
endmodule
''')
            binary = out/(label+'.vvp')
            command = [shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb',
                       '-o', str(binary), str(bench)]
            build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, check=True, timeout=120)
            (out/(label+'_build.log')).write_text(build.stdout)
            result = subprocess.run([shutil.which('vvp') or 'vvp', str(binary)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, check=True, timeout=120)
            run_log = out/(label+'_four_state.log')
            run_log.write_text(result.stdout)
            count = re.search(r'QUEUED_PREVIEW_FOUR_STATE_PASS checks=(\d+)', result.stdout)
            assert count is not None
            four_state.append(dict(mode=mode, set_width=width, line_shift=shift,
                                   checks=int(count[1]), passed=True, log_sha256=digest(run_log)))
            print(label, 'PASS', count[1], flush=True)
    assert all(digest(Path(path))==expected for path,expected in hashes.items())
    (out/'summary.json').write_text(json.dumps(dict(
        passed=True, source_sha256=hashes, runner_sha256=digest(Path(__file__)),
        formal=formal, four_state=four_state,
        four_state_comparisons=sum(row['checks'] for row in four_state)), indent=2)+'\n')


if __name__ == '__main__':
    main()
