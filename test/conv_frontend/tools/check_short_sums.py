#!/usr/bin/env python3
"""验证实际行偏移和历史位置加法器的完整结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'test/frontend_pipeline'))
from source_sections import read_module

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rtl,source=read_module(root,'geometry')
    helper=root/'rtl/common/parallel_prefix_add.sv'
    blocks=[]
    for name in ('u_row_bias','u_history_sum'):
        match=re.search(r'parallel_prefix_add #\([^;]*?\) '+name+r' \([^;]*?\);',source,re.S)
        if match is None:raise RuntimeError('Missing arithmetic instance '+name)
        blocks.append(match.group(0))
    model=out/'short_sums.sv'
    model.write_text("""module comparison(
 input logic [15:0] last_x,p_delta,
 input logic [17:0] retire_i_a,retire_i_b,
 input logic retire_i_carry,
 output logic equivalent
);
 logic [16:0] p_sum;
 logic unused_p_sum_carry;
 logic [17:0] biased_row;
 logic unused_row_carry;
 logic [17:0] expected_history;
 logic [18:0] expected_row;
"""+'\n'.join(blocks)+"""
 assign expected_history={2'b0,last_x}+{2'b0,p_delta};
 assign expected_row={1'b0,retire_i_a}+{1'b0,retire_i_b}+19'(retire_i_carry);
 assign equivalent={unused_p_sum_carry,p_sum}==expected_history &&
                   {unused_row_carry,biased_row}==expected_row;
endmodule
""")
    script,log=out/'proof.ys',out/'proof.log'
    script.write_text('read_slang --top comparison '+shlex.join(map(str,[helper,model]))+
                      '\nprep -top comparison -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w')as output:
        result=subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                              cwd=ROOT,stdout=output,stderr=subprocess.STDOUT,timeout=120)
    if result.returncode or 'SUCCESS!'not in log.read_text():raise RuntimeError(str(log))
    report={'passed':True,'input_bits':69,'output_bits':[18,19],'inputs_constrained':False,
            'source_sha256':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in [rtl,helper]},
            'model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),
            'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()}
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print('SHORT_SUM_PASS')

if __name__=='__main__':main()
