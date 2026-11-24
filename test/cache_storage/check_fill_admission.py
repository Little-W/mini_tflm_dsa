#!/usr/bin/env python3
"""证明填充发送资格的组合等价与全部四态控制组合。"""
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
INPUTS = ('select_fill_capacity_ready','select_prefetch','select_prefetch_ready',
          'select_prefetch_blocked','select_demand_ready','lookup_hit',
          'select_demand_blocked','select_victim_conflict')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--iverilog',default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp',default=shutil.which('vvp') or 'vvp')
    args=parser.parse_args()
    source,out=args.source_root.resolve()/SOURCE,args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    text=source.read_text()
    eligible=re.search(r'assign select_launch_eligible\s*=.*?;',text,re.S).group()
    first=text.index('  always_comb begin\n    select_launch =')
    control=text[first:text.index('    select_way_next=',first)]+'  end\n'
    generated=out/'fill_admission.sv'
    generated.write_text('module proof(input logic '+','.join(INPUTS)+''',
 output logic equivalent,four_state_equal);
 logic select_launch,select_launch_eligible,expected;
''' + eligible+'\n'+control+'''
 always_comb begin
  expected=select_fill_capacity_ready &&
      (select_prefetch?(select_prefetch_ready&&!select_prefetch_blocked):
       (select_demand_ready&&!lookup_hit&&!select_demand_blocked));
  if(expected&&select_victim_conflict)expected=1'b0;
 end
 assign equivalent=select_launch==expected;
 assign four_state_equal=select_launch===expected;
endmodule
''')
    hashes={str(p):digest(p) for p in (source,generated,Path(__file__).resolve())}
    script,log=out/'proof.ys',out/'formal.log'
    script.write_text('read_slang --top proof '+shlex.quote(str(generated))+
        '\nprep -top proof -flatten\ncheck -assert\n'
        'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
            '--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
    if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
    bench=out/'four_state.sv'
    bench.write_text('module tb;\nlogic '+','.join(INPUTS)+''';
 logic equivalent,four_state_equal;
 logic[7:0]values;
 proof dut(.*);
 function automatic logic value(input integer code);
  case(code)0:value=0;1:value=1;2:value=1'bx;default:value=1'bz;endcase
 endfunction
 initial begin
  for(integer sample=0;sample<65536;sample++)begin
   for(integer index=0;index<8;index++)values[index]=value((sample>>(2*index))&3);
'''+'   {'+','.join(INPUTS)+'''}=values;
   #1;
   if(four_state_equal!==1'b1)$fatal(1,"Fill admission mismatch sample=%0d",sample);
  end
  $display("FILL_ADMISSION_FOUR_STATE_PASS checks=65536");$finish;
 end
endmodule
''')
    binary,build,simulation=out/'four_state.vvp',out/'build.log',out/'run.log'
    with build.open('w') as stream:
        subprocess.run([args.iverilog,'-g2012','-s','tb','-o',str(binary),str(generated),str(bench)],
            stdout=stream,stderr=subprocess.STDOUT,check=True)
    with simulation.open('w') as stream:
        subprocess.run([args.vvp,str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
    if 'FILL_ADMISSION_FOUR_STATE_PASS checks=65536' not in simulation.read_text():raise RuntimeError(str(simulation))
    if hashes!={p:digest(p) for p in hashes}:raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        sources_unchanged=True,formal_passed=True,four_state_checks=65536,
        formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)),indent=2)+'\n')
    print('FILL_ADMISSION_PASS formal=1 four_state=65536',flush=True)


if __name__=='__main__':
    main()
