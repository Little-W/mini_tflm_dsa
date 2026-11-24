#!/usr/bin/env python3
"""验证查询边沿保存的地址范围与快照匹配资格。"""
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

from check_tag_stage import block

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model(source):
    direct = block(source, 'if (DEMAND_DEPTH == 1) begin : g_direct_response_lookup')
    capture = block(direct, 'always_ff @(posedge clk) begin')
    qualifier = re.search(r'assign fast_response_conditions\[1\]\s*=.*?;', direct, re.S).group()
    matches = re.search(r'work_snapshot_matches_q\s*<=.*?;', source, re.S).group()
    valid_offset = source.index("      lookup_snapshot_valid <= 1'b0;")
    valid = block(source[source.rfind('always_ff', 0, valid_offset):],
                  'always_ff @(posedge clk or negedge rst_n)')
    states = re.search(r'typedef enum logic\s*\[1:0\]\s*\{[^}]+\}\s*fg_state_t;', source).group()
    return '''module proof(
 input logic clk,rst_n,cfg_valid,cfg_ready,
 input logic[1:0]fg_state,
 input logic lookup_idle_demand_match,lookup_idle_set_match,next_range,
 input logic metadata_enable,metadata_fill_good,lookup_fill_match,spec_read_conflict,
 output logic equivalent,four_state_equal,observed);
''' + states + '''
 typedef struct packed {logic in_range;} request_t;
 request_t lookup_read_request,work_request;
 logic work_snapshot_matches_q,lookup_snapshot_valid,response_snapshot_ready_q;
 logic[1:0]fast_response_conditions;
 assign lookup_read_request.in_range=next_range;
 assign fast_response_conditions[0]=1'b0;
 initial observed=1'b0;
 always_ff @(posedge clk)begin
  work_request<=lookup_read_request;
''' + matches + '''
  observed<=1'b1;
 end
''' + valid + '\n' + capture + '\n' + qualifier + '''
 assign equivalent=!observed || fast_response_conditions[1]==
      (lookup_snapshot_valid&&work_snapshot_matches_q&&work_request.in_range);
 assign four_state_equal=!observed || fast_response_conditions[1]===
      (lookup_snapshot_valid&&work_snapshot_matches_q&&work_request.in_range);
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
    generated = out/'lookup_qualification.sv'
    generated.write_text(model(source.read_text()))
    hashes = {str(path): digest(path) for path in (source, generated, Path(__file__).resolve())}
    script, log = out/'proof.ys', out/'formal.log'
    script.write_text('read_slang --top proof '+shlex.quote(str(generated))+
        '\nprep -top proof -flatten\nasync2sync\nopt_clean\n'
        'sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -prove equivalent 1\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
    if 'Induction step proven: SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    bench = out/'four_state.sv'
    bench.write_text('''module tb;
 logic clk=0,rst_n=0,cfg_valid=0,cfg_ready=0;
 logic[1:0]fg_state=0;
 logic lookup_idle_demand_match=0,lookup_idle_set_match=0,next_range=0;
 logic metadata_enable=0,metadata_fill_good=0,lookup_fill_match=0,spec_read_conflict=0;
 logic equivalent,four_state_equal,observed;
 logic[11:0]pattern;
 integer checks=0;
 proof dut(.*);
 initial begin
  #1;clk=1;#1;clk=0;
  for(integer sample=0;sample<30000;sample++)begin
   for(integer bit_index=0;bit_index<12;bit_index++)begin
    case($urandom_range(0,9))
     0:pattern[bit_index]=1'bx;
     1:pattern[bit_index]=1'bz;
     default:pattern[bit_index]=1'($urandom);
    endcase
   end
   {rst_n,cfg_valid,cfg_ready,fg_state,lookup_idle_demand_match,lookup_idle_set_match,next_range,
      metadata_enable,metadata_fill_good,lookup_fill_match,spec_read_conflict}=pattern;
   #1;
   if(four_state_equal!==1'b1)$fatal(1,"Asynchronous qualification mismatch sample=%0d",sample);
   checks++;
   clk=1;#1;
   if(four_state_equal!==1'b1)$fatal(1,"Sampled qualification mismatch sample=%0d",sample);
   checks++;
   clk=0;
  end
  $display("LOOKUP_QUALIFICATION_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    binary, build, simulation = out/'four_state.vvp', out/'build.log', out/'run.log'
    with build.open('w') as stream:
        subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary),
            str(generated), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    with simulation.open('w') as stream:
        subprocess.run([args.vvp, str(binary)], stdout=stream, stderr=subprocess.STDOUT,
            check=True, timeout=60)
    if 'LOOKUP_QUALIFICATION_FOUR_STATE_PASS checks=60000' not in simulation.read_text():
        raise RuntimeError(str(simulation))
    if hashes != {path: digest(path) for path in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, source_sha256=hashes,
        sources_unchanged=True, formal_passed=True, four_state_checks=60000,
        formal_log_sha256=digest(log), simulation_log_sha256=digest(simulation)), indent=2)+'\n')
    print('LOOKUP_QUALIFICATION_PASS formal=1 four_state=60000', flush=True)


if __name__ == '__main__':
    main()
