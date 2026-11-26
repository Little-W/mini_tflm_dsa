#!/usr/bin/env python3
"""验证完整预读地址匹配的二态等价及四态结果。"""
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/dma/cache/conv_cache_queued_preview.sv'
    initial = digest(source)
    formal, four_state = [], []
    for mode in ('generic', 'fpga'):
        definitions = ('`undef SYNTHESIS\n`undef XILINX_FPGA\n' if mode == 'generic' else
                       '`define SYNTHESIS 1\n`define XILINX_FPGA 1\n')
        for width in (1, 2, 4, 8):
            label = f'{mode}_{width}'
            proof = out / (label + '_proof.sv')
            proof.write_text(definitions + f'''`include "{source}"
module proof(input logic selected, empty, idle, range_value,
             input logic [31:0] request_address, saved_address,
             input logic [{width-1}:0] request_set, saved_set,
             output logic match_result);
  conv_cache_queued_preview #(.p_set_width({width})) dut(
    .i_preview_selected(selected), .i_queue_empty(empty), .i_foreground_idle(idle),
    .i_request_address(request_address), .i_saved_address(saved_address),
    .i_request_set(request_set), .i_saved_set(saved_set), .i_saved_range(range_value),
    .o_match(match_result));
  always_comb assert(match_result == (selected && empty && idle &&
      request_address == saved_address && request_set == saved_set));
endmodule
''')
            script = out / (label + '.ys')
            script.write_text(f'read_slang --top proof {proof}\nsetattr -mod -unset keep_hierarchy\n'
                              'setattr -unset keep_hierarchy\nsetattr -unset keep\n'
                              'prep -top proof -flatten\nchformal -lower\nsat -verify -prove-asserts -show-inputs\n')
            log = out / (label + '_formal.log')
            with log.open('w') as stream:
                subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                '--worker', script], stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            assert 'SUCCESS' in log.read_text()
            formal.append(dict(mode=mode, set_width=width, passed=True,
                               input_constraints=[], log_sha256=digest(log)))
            bench = out / (label + '_tb.sv')
            bench.write_text(definitions + f'''`include "{source}"
module tb;
  localparam integer W={width};
  reg selected, empty, idle, range_value;
  reg [31:0] request_address, saved_address;
  reg [W-1:0] request_set, saved_set;
  wire match_result;
  reg expected;
  integer seed=32'h31c7ad95;
  integer checks=0;
  conv_cache_queued_preview #(.p_set_width(W)) dut(
    .i_preview_selected(selected), .i_queue_empty(empty), .i_foreground_idle(idle),
    .i_request_address(request_address), .i_saved_address(saved_address),
    .i_request_set(request_set), .i_saved_set(saved_set), .i_saved_range(range_value),
    .o_match(match_result));
  function automatic logic value4(input integer code);
    case(code & 3)
      0: value4=1'b0;
      1: value4=1'b1;
      2: value4=1'bx;
      3: value4=1'bz;
    endcase
  endfunction
  task automatic compare;
    #1;
    expected=1'b0;
    case ({{selected,empty,idle,request_address==saved_address,request_set==saved_set}})
      5'b11111: expected=1'b1;
      default: begin end
    endcase
    case (range_value)
      1'b0,1'b1: begin end
      default: expected=1'b0;
    endcase
    if(match_result !== expected) $fatal(1,"preview result mismatch checks=%0d",checks);
    checks++;
  endtask
  initial begin
    for(integer control=0;control<256;control++) begin
      selected=value4(control);empty=value4(control>>2);
      idle=value4(control>>4);range_value=value4(control>>6);
      request_address=32'h36ac9e51;saved_address=request_address;
      request_set=W'(7);saved_set=request_set;
      compare();
      for(integer bit_index=0;bit_index<32;bit_index++) begin
        for(integer code=0;code<4;code++) begin
          saved_address=request_address;saved_address[bit_index]=value4(code);
          compare();
        end
      end
      saved_address=request_address;
      for(integer bit_index=0;bit_index<W;bit_index++) begin
        for(integer code=0;code<4;code++) begin
          saved_set=request_set;saved_set[bit_index]=value4(code);
          compare();
        end
      end
    end
    for(integer trial=0;trial<20000;trial++) begin
      request_address=$random(seed);saved_address=request_address;
      request_set=$random(seed);saved_set=request_set;
      selected=1;empty=1;idle=1;range_value=trial[0];
      case(trial%8)
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
      endcase
      compare();
    end
    $display("QUEUED_PREVIEW_FOUR_STATE_PASS checks=%0d",checks);
    $finish;
  end
endmodule
''')
            binary = out / (label + '.vvp')
            command = [shutil.which('iverilog') or 'iverilog', '-g2012', '-s', 'tb',
                       '-o', str(binary), str(bench)]
            build = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, check=True, timeout=120)
            (out / (label + '_build.log')).write_text(build.stdout)
            result = subprocess.run([shutil.which('vvp') or 'vvp', str(binary)],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, check=True, timeout=120)
            run_log = out / (label + '_four_state.log')
            run_log.write_text(result.stdout)
            count = re.search(r'QUEUED_PREVIEW_FOUR_STATE_PASS checks=(\d+)', result.stdout)
            assert count is not None
            four_state.append(dict(mode=mode, set_width=width, checks=int(count[1]),
                                   passed=True, log_sha256=digest(run_log)))
            print(label, 'PASS', count[1], flush=True)
    assert digest(source) == initial
    (out / 'summary.json').write_text(json.dumps(dict(
        passed=True, source_sha256={str(source): initial}, runner_sha256=digest(Path(__file__)),
        formal=formal, four_state=four_state,
        four_state_comparisons=sum(row['checks'] for row in four_state)), indent=2) + '\n')


if __name__ == '__main__':
    main()
