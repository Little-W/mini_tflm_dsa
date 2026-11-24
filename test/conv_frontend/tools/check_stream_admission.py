#!/usr/bin/env python3
"""证明描述符交接、流式更新及错误响应具有相同的逐周期更新事件。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('rtl/npu/conv/conv_im2col_frontend.sv')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assignment(source, name):
    return re.search(r'\bassign\s+'+re.escape(name)+r'\s*=.*?;', source, re.S).group()


def normalize_stream_control(source):
    """以相同事件的嵌套形式检查原有寄存器赋值及其内部条件。"""
    start = '''        stream_response_error: begin
          error<=1;tile_error<=1;
        end
        stream_operation_accept: begin'''
    expanded = '''        (!tile_commit && (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] ||
                          state[$clog2(ZERO_STREAM)])): begin
          if (state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) begin
            error<=1;tile_error<=1;
          end else if (wr_valid && wr_ready) begin'''
    stop = '''        (!tile_commit && stream_response_error !== 1'b1 && stream_operation_accept !== 1'b1 &&
          (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)])): ;'''
    if source.count(start) != 1 or source.count(stop) != 1:
        raise ValueError('流式更新分支与已验证事件结构不同')
    return source.replace(start, expanded, 1).replace(stop, '        end', 1)


def model(source):
    controls = '\n'.join(assignment(source, name) for name in (
        'wr_valid', 'wr_last', 'stream_response_error', 'stream_output_accept',
        'stream_operation_accept', 'finishing_tile', 'tile_admission_ready',
        'tile_ready_context', 'tile_ready', 'descriptor_commit_eligible', 'descriptor_state_context'))
    return '''module proof #(parameter REGISTER_DESCRIPTOR=0)(
 input logic[4:0]state_index,
 input logic cfg_valid,cfg_ready,tile_valid,tile_ready_static,tile_prepared_valid,error,
 input logic wr_ready,cache_rsp_valid,cache_rsp_error,row_last_q,chunk_reaches_end,
 output logic equivalent,output logic[2:0]actual_event,expected_event);
 import conv_im2col_frontend_pkg::*;
 logic[26:0]state;
 logic wr_valid,wr_last,stream_response_error,stream_output_accept,stream_operation_accept;
 logic finishing_tile,tile_admission_ready,tile_ready_context,tile_ready,tile_commit;
 logic descriptor_commit_eligible,descriptor_state_context;
 wire cache_rsp_success=cache_rsp_valid&&!cache_rsp_error;
 wire cache_rsp_failure=cache_rsp_valid&&cache_rsp_error;
 wire streaming=state[$clog2(WAIT_WORD)]||state[$clog2(STREAM)]||state[$clog2(ZERO_STREAM)];
 wire other_state=|(state & ~(IDLE|DESCRIPTOR_CHECK|WAIT_WORD|STREAM|ZERO_STREAM));
 assign state=27'b1<<state_index;
''' + controls + '''
 assign tile_commit=REGISTER_DESCRIPTOR?
     tile_prepared_valid&&!error&&(state[$clog2(IDLE)]||finishing_tile):tile_valid&&tile_ready;
 always_comb begin
  expected_event=3'd0;
  case(1'b1)
   (cfg_valid&&cfg_ready):expected_event=3'd1;
   tile_commit:expected_event=3'd2;
   state[$clog2(DESCRIPTOR_CHECK)]:expected_event=3'd3;
   (!tile_commit&&streaming):begin
    if(state[$clog2(WAIT_WORD)]&&cache_rsp_valid&&cache_rsp_error)expected_event=3'd4;
    else if(wr_valid&&wr_ready)expected_event=3'd5;
   end
   other_state:expected_event=3'd0;
   (state[$clog2(IDLE)]&&!(cfg_valid&&cfg_ready)&&!tile_commit):expected_event=3'd0;
   default:expected_event=3'd6;
  endcase
 end
 always_comb begin
  actual_event=3'd0;
  case(1'b1)
   (cfg_valid&&cfg_ready):actual_event=3'd1;
   tile_commit:actual_event=3'd2;
   state[$clog2(DESCRIPTOR_CHECK)]:actual_event=3'd3;
   stream_response_error:actual_event=3'd4;
   stream_operation_accept:actual_event=3'd5;
   (!tile_commit && stream_response_error !== 1'b1 && stream_operation_accept !== 1'b1 && streaming):actual_event=3'd0;
   other_state:actual_event=3'd0;
   (state[$clog2(IDLE)]&&!(cfg_valid&&cfg_ready)&&!tile_commit):actual_event=3'd0;
   default:actual_event=3'd6;
  endcase
 end
 assign equivalent=actual_event===expected_event;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, package = root/SOURCE, root/'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    text = source.read_text()
    normalize_stream_control(text)
    generated = out/'stream_admission.sv'
    generated.write_text(model(text).replace('always_comb', 'always @*'))
    hashes = {str(path): digest(path) for path in (source, package, generated, Path(__file__).resolve())}
    cases = []
    for registered in (0, 1):
        name = f'descriptor{registered}'
        script, log = out/(name+'.ys'), out/(name+'.formal.log')
        script.write_text(f'read_slang --top proof -GREGISTER_DESCRIPTOR={registered} '+
            shlex.join(map(str, (package, generated)))+'\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        bench = out/(name+'.sv')
        bench.write_text('''module tb;
 logic[4:0]state_index;
 logic cfg_valid,cfg_ready,tile_valid,tile_ready_static,tile_prepared_valid,error;
 logic wr_ready,cache_rsp_valid,cache_rsp_error,row_last_q,chunk_reaches_end,equivalent;
 logic[2:0]actual_event,expected_event;
 logic[10:0]pattern;
 proof #(.REGISTER_DESCRIPTOR('''+str(registered)+''')) dut(.*);
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   for(integer bit_index=0;bit_index<11;bit_index++)begin
    case($urandom_range(0,9))
     0:pattern[bit_index]=1'bx;
     1:pattern[bit_index]=1'bz;
     default:pattern[bit_index]=1'($urandom);
    endcase
   end
   {cfg_valid,cfg_ready,tile_valid,tile_ready_static,tile_prepared_valid,error,
      wr_ready,cache_rsp_valid,cache_rsp_error,row_last_q,chunk_reaches_end}=pattern;
   state_index=5'(sample%28);
   #1;
   if(equivalent!==1'b1)$fatal(1,"Stream event mismatch sample=%0d state=%0d actual=%d expected=%d pattern=%b",
       sample,state_index,actual_event,expected_event,pattern);
  end
  $display("STREAM_ADMISSION_FOUR_STATE_PASS checks=65536");$finish;
 end
endmodule
''')
        binary, build, simulation = out/(name+'.vvp'), out/(name+'.build.log'), out/(name+'.run.log')
        with build.open('w') as stream:
            subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary),
                *map(str, (package, generated, bench))], stdout=stream, stderr=subprocess.STDOUT, check=True)
        with simulation.open('w') as stream:
            subprocess.run([args.vvp, str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                check=True, timeout=60)
        cases.append(dict(register_descriptor=registered, formal_passed=True, four_state_checks=65536,
            formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation)))
        print('STREAM_ADMISSION_PASS', name, flush=True)
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        sources_unchanged=True, cases=cases), indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
