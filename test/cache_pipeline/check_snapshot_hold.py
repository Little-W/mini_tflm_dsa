#!/usr/bin/env python3
"""验证替换快照有效位的完整状态转移，覆盖二值和四态控制输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from rtl_source_view import controller_module, module_definition, read_sources, source_manifest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/cache/conv_windowed_cache.sv')
sys.path.insert(0, str(ROOT / 'test'))
from reference_sources import read_reference_file

SIGNALS = (
    'rst_n', 'cfg_valid', 'cfg_ready', 'select_stage_valid',
    'metadata_fill', 'fill_set_match', 'select_hint_busy', 'select_request_set_match',
    'select_prefetch', 'pf_pending', 'select_prefetch_address_matches', 'pf_hit',
    'pf_in_flight', 'foreground_miss', 'select_demand_address_matches', 'lookup_hit',
    'lookup_range', 'select_decision_valid', 'fill_idle', 'fill_success', 'pf_match_ready',
    'req_fire', 'select_victim_conflict', 'bypass_q', 'lookup_ready', 'completing_demand',
    'select_launch_candidate', 'candidate_metadata_busy',
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model(name, source):
    source = controller_module(source)
    marker = ('  logic select_stage_next_valid;' if '  logic select_stage_next_valid;' in source
              else '  (* keep = 1 *) logic select_snapshot_usable, select_retire_ready;')
    start = source.index(marker)
    end = source.index('  // Separate synchronous metadata reads', start)
    body = source[start:end]
    metadata_start = source.index('  assign select_fill_busy =')
    metadata_end = source.index('  // 各端口地址独立保存', metadata_start)
    body = source[metadata_start:metadata_end] + body
    body = body.replace('fill_set == select_set', 'fill_set_match')
    body = body.replace('fg_state == FG_MISS', 'foreground_miss')
    body = body.replace('fill_state == F_IDLE', 'fill_idle')
    body = body.replace('always_ff @(posedge clk or negedge rst_n)', 'always_comb')
    body = body.replace('select_stage_valid <=', 'observed =')
    return f'''module {name}(input logic [{len(SIGNALS)-1}:0] stimulus, output logic observed);
  logic {','.join(SIGNALS)};
  logic select_metadata_busy, select_fill_busy;
  assign {{{','.join(SIGNALS)}}}=stimulus;
{body}
endmodule
'''


def bench():
    return f'''module tb;
  localparam integer W={len(SIGNALS)};
  logic [W-1:0] stimulus, saved;
  logic expected, actual;
  logic [31:0] random_state=32'hcd341ea7;
  integer checks=0;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  task automatic check;
    #1;
    if (expected !== actual)
      $fatal(1,"SNAPSHOT_HOLD_MISMATCH stimulus=%b expected=%b actual=%b",stimulus,expected,actual);
    checks++;
  endtask
  initial begin
    for (integer trial=0;trial<4096;trial++) begin
      for (integer bit_index=0;bit_index<W;bit_index++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        stimulus[bit_index]=random_state[0];
      end
      if (trial%32==0) stimulus='0;
      if (trial%32==1) stimulus='1;
      if (trial%32==2) stimulus={{W{{1'b1}}}} ^ (1 << (trial%W));
      saved=stimulus;check();
      for (integer bit_index=0;bit_index<W;bit_index++) begin
        stimulus=saved;stimulus[bit_index]=1'bx;check();
        stimulus=saved;stimulus[bit_index]=1'bz;check();
      end
      for (integer bit_index=0;bit_index<W;bit_index++) begin
        random_state={{random_state[30:0],random_state[31]^random_state[21]^random_state[1]^random_state[0]}};
        case (random_state[1:0])
          0:stimulus[bit_index]=1'b0;
          1:stimulus[bit_index]=1'b1;
          2:stimulus[bit_index]=1'bx;
          3:stimulus[bit_index]=1'bz;
        endcase
      end
      check();
    end
    stimulus='x;check();stimulus='z;check();
    $display("SNAPSHOT_HOLD_PASS checks=%0d", checks);$finish;
  end
endmodule
'''


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str,command)),cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--reference-ref',default='9e3e5d6a6f47befe6c86aceacad7999923206458')
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    current=read_sources(ROOT,SOURCE)
    original=read_reference_file(ROOT,args.reference_ref,SOURCE,text=True)
    support='\n'.join(module_definition(current,name) for name in
                      ('conv_cache_snapshot_hold','conv_cache_snapshot_valid','conv_cache_select_busy'))
    modules=model('reference',original)+model('candidate',current)+support+'\n'
    proof=out/'comparison.sv'
    proof.write_text(modules+f'''module comparison(input logic [{len(SIGNALS)-1}:0] stimulus,output logic equivalent);
  logic expected,actual;
  reference u_reference(.*,.observed(expected));
  candidate u_candidate(.*,.observed(actual));
  assign equivalent=expected==actual;
endmodule
''')
    logs=[]
    for label,options in [('generic',''),('fpga','-DSYNTHESIS=1 -DXILINX_FPGA=1')]:
        script=out/f'{label}.ys';log=out/f'{label}.log'
        script.write_text(f'read_slang --top comparison {options} '+shlex.quote(str(proof))+
            '\nprep -top comparison -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        logs.append(dict(profile=label,passed=True,log_sha256=digest(log)))
    four=out/'four_state.sv';four.write_text(modules+bench())
    run(['iverilog','-g2012','-s','tb','-o',out/'simulation',four],out/'build.log')
    run(['vvp',out/'simulation'],out/'run.log')
    match=re.search(r'SNAPSHOT_HOLD_PASS checks=(\d+)',(out/'run.log').read_text())
    assert match and int(match[1])==4096*(2*len(SIGNALS)+2)+2
    assert current==read_sources(ROOT,SOURCE)
    result=dict(passed=True,actual_rtl_expressions=True,external_inputs_constrained=False,
                reference_ref=args.reference_ref,source_sha256=source_manifest(ROOT,SOURCE),
                profiles=logs,four_state_checks=int(match[1]),proof_sha256=digest(proof),
                four_state_log_sha256=digest(out/'run.log'))
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('passed','profiles','four_state_checks')}))


if __name__=='__main__':
    main()
