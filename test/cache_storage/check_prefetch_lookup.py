#!/usr/bin/env python3
"""证明普通地址及窗口索引的并行组号匹配。"""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    source, out = args.source_root.resolve()/SOURCE, args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    text = source.read_text()
    first = text.index('  (* keep = 1 *) logic [1:0] pf_snapshot_set_matches;')
    control = text[first:text.index('  wire pf_match_ready', first)]
    function = re.search(r'function automatic logic \[SI-1:0\] cache_set\b.*?endfunction', text, re.S).group()
    generated = out/'prefetch_lookup.sv'
    generated.write_text('''module proof #(parameter SI=4,LB=7)(
 input logic[31:0]pf_addr,pf_index,
 input logic[SI-1:0]pf_snapshot_set,
 input logic windowed_q,pf_index_valid,pf_snapshot_valid,
 output logic equivalent,four_state_equal);
''' + function + '\n' + control + '''
 wire reference_result=pf_snapshot_valid &&
      pf_snapshot_set==cache_set(pf_addr,windowed_q&&pf_index_valid,pf_index);
 assign equivalent=pf_lookup_ready==reference_result;
 assign four_state_equal=pf_lookup_ready===reference_result;
endmodule
''')
    hashes = {str(path):digest(path) for path in (source, generated, Path(__file__).resolve())}
    cases=[]
    for si, lb in ((1,3),(3,4),(4,7),(5,8),(7,8)):
        name=f's{si}_l{lb}'
        script,log=out/(name+'.ys'),out/(name+'.formal.log')
        script.write_text(f'read_slang --top proof -GSI={si} -GLB={lb} '+shlex.quote(str(generated))+
            '\nprep -top proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                '--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=120)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
        bench=out/(name+'.sv')
        bench.write_text('''module tb;
 localparam SI='''+str(si)+''',LB='''+str(lb)+''',WIDTH=67+SI;
 logic[31:0]pf_addr,pf_index;
 logic[SI-1:0]pf_snapshot_set;
 logic windowed_q,pf_index_valid,pf_snapshot_valid,equivalent,four_state_equal;
 logic[WIDTH-1:0]pattern;
 proof #(.SI(SI),.LB(LB)) dut(.*);
 initial begin
  for(integer sample=0;sample<20000;sample++)begin
   for(integer bit_index=0;bit_index<WIDTH;bit_index++)begin
    case($urandom_range(0,9))
     0:pattern[bit_index]=1'bx;
     1:pattern[bit_index]=1'bz;
     default:pattern[bit_index]=1'($urandom);
    endcase
   end
   {pf_addr,pf_index,pf_snapshot_set,windowed_q,pf_index_valid,pf_snapshot_valid}=pattern;
   #1;
   if(four_state_equal!==1'b1)$fatal(1,"Prefetch set mismatch sample=%0d",sample);
  end
  $display("PREFETCH_LOOKUP_FOUR_STATE_PASS checks=20000");$finish;
 end
endmodule
''')
        binary,build,simulation=out/(name+'.vvp'),out/(name+'.build.log'),out/(name+'.run.log')
        with build.open('w') as stream:
            subprocess.run([args.iverilog,'-g2012','-s','tb','-o',str(binary),str(generated),str(bench)],
                stdout=stream,stderr=subprocess.STDOUT,check=True)
        with simulation.open('w') as stream:
            subprocess.run([args.vvp,str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=60)
        if 'PREFETCH_LOOKUP_FOUR_STATE_PASS checks=20000' not in simulation.read_text():raise RuntimeError(str(simulation))
        cases.append(dict(sets=2**si,line_bytes=2**lb,formal_passed=True,four_state_checks=20000,
            formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)))
        print('PREFETCH_LOOKUP_PASS',name,flush=True)
    if hashes!={path:digest(path) for path in hashes}:raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,
        sources_unchanged=True,cases=cases),indent=2)+'\n')


if __name__=='__main__':
    main()
