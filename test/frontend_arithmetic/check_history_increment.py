#!/usr/bin/env python3
"""验证历史行递增的完整输出及四态分组传播。"""
from __future__ import annotations

from formal_compilation import slang_command
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, bench, digest, run


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--source',type=Path,default=ROOT/'rtl/npu/conv/conv_history_row_increment.sv')
    parser.add_argument('--reference',default='54a96b45')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    original=subprocess.check_output(['git','show',args.reference+':rtl/npu/conv/conv_im2col_geometry.sv'],cwd=ROOT,text=True)
    match=re.search(r'  parallel_prefix_add #\([^;]*?\) u_history_next_y \(.*?\n  \);',original,re.S)
    if match is None:raise ValueError('历史行递增语句未找到')
    generated=out/'history_increment.sv';generated.write_text('''module match_proof(input logic [15:0] i_a,i_b,output logic equivalent);
logic [15:0] i_last_y;
logic [16:0] history_next_y,actual_row;
logic unused_history_next_y_carry,actual_carry;
assign i_last_y=i_a;
'''+match.group(0)+'''
conv_history_row_increment u_actual(.i_row(i_last_y),.o_row(actual_row),.o_carry(actual_carry));
assign equivalent={actual_carry,actual_row}==={unused_history_next_y_carry,history_next_y};
endmodule
''')
    dependencies=runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources=dependencies([args.source.resolve(),generated],ROOT);hashes={str(p):digest(p) for p in sources}
    tb=out/'tb.sv';tb.write_text(bench(16));formal=[];simulations=[]
    for synthesis in (0,1):
        name='synthesis'+str(synthesis);options=['-DSYNTHESIS=1','-DXILINX_FPGA=1'] if synthesis else []
        script=out/(name+'.ys');log=out/(name+'.log')
        script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options,*map(str,sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top match_proof -flatten\ncheck -assert\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():raise ValueError('历史行递增形式证明未完成')
        formal.append(dict(synthesis=synthesis,passed=True,log_sha256=digest(log)))
        binary=out/(name+'.vvp');run(['iverilog','-g2012',*options,'-s','tb','-o',binary,*sources,tb],out/('compile_'+name+'.log'))
        log=out/('simulation_'+name+'.log');run(['vvp',binary],log)
        if 'WORD_MATCH_PASS width=16 checks=2146' not in log.read_text():raise ValueError('历史行递增四态比较未完成')
        simulations.append(dict(synthesis=synthesis,passed=True,checks=2146,log_sha256=digest(log)))
    assert all(digest(path)==value for path,value in hashes.items())
    report=dict(passed=True,reference=args.reference,input_assumptions=[],source_sha256=hashes,
        reference_sha256=hashlib.sha256(original.encode()).hexdigest(),formal=formal,four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('HISTORY_INCREMENT_PASS formal=2 four_state=4292')


if __name__=='__main__':main()
