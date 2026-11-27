#!/usr/bin/env python3
"""使用完整前端的实际连接证明运行寄存器事件唯一性及状态独热保持。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from run_formal import ROOT, SOURCE
from run_four_state import port_declarations
from protocol_model import case_conditions, observation_logic


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def instrument_frontend(source, runtime):
    match = re.search(r'module conv_im2col_frontend\s*#\((.*?)\)\s*\((.*?)\);', source, re.S)
    declarations = []
    locals_list = []
    for line in match[2].splitlines():
        declaration = line.split('//',1)[0].strip().rstrip(',')
        if declaration.startswith('input '):
            declarations.append('  '+declaration)
        elif declaration.startswith('output '):
            locals_list.append('  '+declaration.removeprefix('output ')+';')
    declarations += ['  output logic formal_main_unique', '  output logic formal_arithmetic_unique',
                     '  output logic formal_state_onehot', '  output logic formal_next_state_onehot',
                     '  output logic formal_state_idle']
    header = source[:match.start(2)]+'\n'+',\n'.join(declarations)+'\n);\n'
    locals_text = '\n'.join(locals_list)
    result = header+locals_text+'\n'+source[match.end():]
    observations = observation_logic(runtime,'u_runtime_registers.')+'''
  assign formal_state_idle = state == IDLE;
  assign formal_state_onehot = state != 27'd0 && (state & (state-27'd1)) == 27'd0;
  assign formal_next_state_onehot = !state_update ||
      (selected_state != 27'd0 && (selected_state & (selected_state-27'd1)) == 27'd0);
'''
    return result.replace('endmodule', observations+'\nendmodule', 1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--lanes',type=int,choices=(8,16),default=8)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/SOURCE
    frontend=ROOT/'rtl/npu/conv/conv_im2col_frontend.sv'
    source=out/'observed_frontend.sv'
    source.write_text(instrument_frontend(frontend.read_text(),runtime.read_text()))
    resolver=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources=resolver['with_dependencies']([source],ROOT)
    files=resolver['input_files']([*sources,frontend],ROOT)
    hashes={str(path):digest(path) for path in files}
    runs=[]
    for registered in (0,1):
        options=['-GSIZE=16','-GSLOT_W=6','-GLANES='+str(args.lanes),'-GBUS_WIDTH=64','-GCACHE_SETS=16',
                 '-GCACHE_WAYS=2','-GLINE_BYTES=128','-GCACHE_RESPONSE_DEPTH=2',
                 '-GREGISTER_DESCRIPTOR='+str(registered)]
        script=out/f'events_d{registered}.ys';log=out/f'events_d{registered}.log'
        script.write_text(shlex.join(['read_slang','--top','conv_im2col_frontend','-DSYNTHESIS=1',
            '-DXILINX_FPGA=1','-I'+str(ROOT/'include'),*options,*map(str,sources)])+'\n'+
            'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nsetattr -unset keep\n'+
            'prep -top conv_im2col_frontend -flatten\nasync2sync\nopt_clean\n'+
            'memory_map\nopt -full\n'+
            'sat -verify -seq 1 -set rst_n 0 -prove formal_state_onehot 1 -prove formal_state_idle 1\n'+
            'expose -input conv_im2col_frontend/w:state\nopt_clean\n'+
            'sat -verify -seq 1 -set formal_state_onehot 1 '+
            '-prove formal_main_unique 1 -prove formal_arithmetic_unique 1 '+
            '-prove formal_next_state_onehot 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],
                cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=480)
        if log.read_text().count('SAT proof finished - no model found: SUCCESS!') != 2:
            raise RuntimeError('生产前端事件和状态保持证明未完成')
        row=dict(register_descriptor=registered,lanes=args.lanes,reset_proven=True,passed=True,log_sha256=digest(log))
        runs.append(row);print(json.dumps(row),flush=True)
    if any(digest(path)!=value for path,value in hashes.items()):
        raise RuntimeError('证明过程中生产前端源码发生变化')
    report=dict(passed=True,initial_state='IDLE',reset_sat_proven=True,lanes=args.lanes,
        state_invariant='state != 0 && (state & (state - 1)) == 0',
        next_state_onehot_preserved=True,other_state_and_inputs_constrained=False,
        runtime_case_conditions=case_conditions(runtime.read_text()),
        source_sha256=hashes,runner_sha256=digest(__file__),runs=runs)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
