#!/usr/bin/env python3
"""比较完整十七位区间判断的二态关系与四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'rtl/npu/conv/vector_interval_bound.sv'
REFERENCE = '9e3e5d6a6f47befe6c86aceacad7999923206458'
MODES = (('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']), ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']))


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=300)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=out/'reference_interval.sv'
    reference.write_text(subprocess.check_output(
        ['git','show',REFERENCE+':rtl/npu/conv/vector_interval_bound.sv'],cwd=ROOT,text=True).replace(
            'module vector_interval_bound (','module reference_interval (',1))
    resolve=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    reference_sources=resolve([reference],ROOT)
    candidate_sources=resolve([SOURCE],ROOT)
    source_hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in candidate_sources}
    bench=out/'tb.sv'
    bench.write_text('''`timescale 1ns/1ps
// 输入包括负坐标、相等与反向区间、符号边界及逐位未知值。
module tb;
reg signed [16:0] i_coordinate, i_minimum, i_maximum;
wire actual,expected;
integer checks=0;
integer seed=261127;
reference_interval ref_dut(.*,.o_inside(expected));
vector_interval_bound dut(.*,.o_inside(actual));
initial begin
    for(integer sample=0;sample<262144;sample=sample+1)begin
        i_coordinate=$random(seed);i_minimum=$random(seed);i_maximum=$random(seed);
        case(sample%16)
            0:i_coordinate=i_minimum;
            1:i_coordinate=i_maximum;
            2:i_minimum=i_maximum;
            3:begin i_minimum=-17'sd65536;i_maximum=17'sd65535;end
            4:i_coordinate[(sample>>4)%17]=1'bx;
            5:i_minimum[(sample>>4)%17]=1'bx;
            6:i_maximum[(sample>>4)%17]=1'bx;
            7:i_coordinate[(sample>>4)%17]=1'bz;
            8:i_minimum[(sample>>4)%17]=1'bz;
            9:i_maximum[(sample>>4)%17]=1'bz;
            10:begin i_minimum='x;i_maximum='z;end
            11:begin i_coordinate='x;i_minimum=0;i_maximum=1;end
            default:begin end
        endcase
        #1;
        if(actual!==expected)$fatal(1,"区间结果不一致，检查 %0d",checks);
        checks=checks+1;
    end
    $display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')
    results=[]
    for mode,flags in MODES:
        commands=[]
        for label,top,sources in [('reference','reference_interval',reference_sources),
                                 ('candidate','vector_interval_bound',candidate_sources)]:
            commands += ['read_slang --top '+top+' '+shlex.join([*flags,*map(str,sources)]),
                         'setattr -mod -unset keep_hierarchy','setattr -unset keep_hierarchy',
                         'prep -top '+top+' -flatten','opt -full',
                         'rename -top '+label,'design -stash '+label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate proof','hierarchy -top proof',
                     'equiv_simple','equiv_status -assert']
        script=out/(mode+'.ys');script.write_text('\n'.join(commands)+'\n')
        proof_log=out/(mode+'_formal.log')
        execute([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],proof_log)
        executable=out/(mode+'.vvp')
        execute(['iverilog','-g2012',*flags,'-s','tb','-o',executable,
                 *list(dict.fromkeys([*reference_sources,*candidate_sources])),bench],out/(mode+'_compile.log'))
        simulation_log=out/(mode+'_four_state.log')
        execute(['vvp',executable],simulation_log)
        if 'PASS comparisons=262144' not in simulation_log.read_text():
            raise RuntimeError(str(simulation_log))
        results.append({'mode':mode,'formal':True,'four_state_comparisons':262144,
                        'proof_log_sha256':hashlib.sha256(proof_log.read_bytes()).hexdigest()})
        print(mode+' PASS',flush=True)
    if source_hashes != {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in candidate_sources}:
        raise RuntimeError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps({'passed':True,'reference_revision':REFERENCE,
        'input_assumptions':[],'source_sha256':source_hashes,'modes':results},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
