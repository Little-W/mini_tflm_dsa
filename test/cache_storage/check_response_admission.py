#!/usr/bin/env python3
"""证明缓存成功及错误返回资格，并检查四态输入的传播结果。"""
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

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(source):
    first = source.index('  assign core_rsp_valid=')
    last = source.index('  assign response_pop=', first)
    control = source[first:last]
    states = re.search(r'typedef enum logic\s*\[1:0\]\s*\{[^}]+\}\s*fg_state_t;', source).group()
    return '''module proof #(parameter DEMAND_DEPTH=1,
 parameter DQ_AW=DEMAND_DEPTH<=1?1:$clog2(DEMAND_DEPTH),
 parameter DQ_CW=$clog2(DEMAND_DEPTH+1))(
 input logic[1:0]fg_state,
 input logic[DQ_CW-1:0]response_count,
 input logic[DQ_AW-1:0]head,
 input logic[DEMAND_DEPTH-1:0]queued_errors,
 input logic fast_eligible,response_error,rsp_ready,
 output logic equivalent,four_state_equal);
 localparam READ_WIDTH=32;
''' + states + '''
 wire[DQ_AW-1:0]response_head=DEMAND_DEPTH==1?DQ_AW'(0):head;
 wire fast_hit_response=fg_state==FG_IDLE && fast_eligible &&
      response_count<DQ_CW'(DEMAND_DEPTH);
 wire[READ_WIDTH-1:0]core_rsp_data='0;
 wire[READ_WIDTH-1:0]response_queue_data[DEMAND_DEPTH];
 wire response_queue_error[DEMAND_DEPTH];
 for(genvar item=0;item<DEMAND_DEPTH;item++)begin:g_queue
  assign response_queue_data[item]='0;
  assign response_queue_error[item]=queued_errors[item];
 end
 logic core_rsp_valid,core_rsp_error,core_rsp_ready;
 logic rsp_valid,rsp_error,rsp_success,rsp_failure,response_push;
 logic[READ_WIDTH-1:0]rsp_data;
''' + control + '''
 assign equivalent={rsp_success,rsp_failure}==
      {rsp_valid&&!rsp_error,rsp_valid&&rsp_error};
 assign four_state_equal={rsp_success,rsp_failure}===
      {rsp_valid&&!rsp_error,rsp_valid&&rsp_error};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    source, out = args.source_root.resolve()/SOURCE, args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    generated = out/'response_admission.sv'
    generated.write_text(model(source.read_text()))
    hashes = {str(path): digest(path) for path in (source, generated, Path(__file__).resolve())}
    cases = []
    for depth in (1, 2, 4):
        name = f'depth{depth}'
        script, log = out/(name+'.ys'), out/(name+'.formal.log')
        script.write_text(f'read_slang --top proof -GDEMAND_DEPTH={depth} '+shlex.quote(str(generated))+
            '\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        bench = out/(name+'.sv')
        bench.write_text('''module tb;
 localparam DEMAND_DEPTH='''+str(depth)+''';
 localparam DQ_AW=DEMAND_DEPTH<=1?1:$clog2(DEMAND_DEPTH);
 localparam DQ_CW=$clog2(DEMAND_DEPTH+1);
 localparam WIDTH=2+DQ_CW+DQ_AW+DEMAND_DEPTH+3;
 logic[1:0]fg_state;
 logic[DQ_CW-1:0]response_count;
 logic[DQ_AW-1:0]head;
 logic[DEMAND_DEPTH-1:0]queued_errors;
 logic fast_eligible,response_error,rsp_ready,equivalent,four_state_equal;
 logic[WIDTH-1:0]pattern;
 proof #(.DEMAND_DEPTH(DEMAND_DEPTH)) dut(.*);
 initial begin
  for(integer sample=0;sample<30000;sample++)begin
   for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
    case($urandom_range(0,9))
     0:pattern[bit_index]=1'bx;
     1:pattern[bit_index]=1'bz;
     default:pattern[bit_index]=1'($urandom);
    endcase
   end
   {fg_state,response_count,head,queued_errors,fast_eligible,response_error,rsp_ready}=pattern;
   #1;
   if(four_state_equal!==1'b1)$fatal(1,"Response admission mismatch sample=%0d",sample);
  end
  $display("RESPONSE_ADMISSION_FOUR_STATE_PASS checks=30000");$finish;
 end
endmodule
''')
        binary, build, simulation = out/(name+'.vvp'), out/(name+'.build.log'), out/(name+'.run.log')
        with build.open('w') as stream:
            subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary),
                str(generated), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        with simulation.open('w') as stream:
            subprocess.run([args.vvp, str(binary)], stdout=stream, stderr=subprocess.STDOUT,
                check=True, timeout=60)
        if 'RESPONSE_ADMISSION_FOUR_STATE_PASS checks=30000' not in simulation.read_text():
            raise RuntimeError(str(simulation))
        cases.append(dict(depth=depth, formal_passed=True, four_state_checks=30000,
            formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation)))
        print('RESPONSE_ADMISSION_PASS', name, flush=True)
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        sources_unchanged=True, cases=cases), indent=2, ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
