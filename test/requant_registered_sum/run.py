#!/usr/bin/env python3
"""用官方 DSP 模型证明定宽寄存相加及任意时钟使能下的保持行为。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script '+shlex.quote(str(args.worker)));return
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    source_path=ROOT/'rtl/npu/writeback/vec_requant.sv'
    source=source_path.read_text()
    helper=re.search(r'^module requant_registered_sum\b.*?^endmodule',source,re.M|re.S).group(0)
    helper_path=out/'registered_sum.sv';helper_path.write_text(helper+'\n')
    import pyosys
    library=Path(pyosys.__file__).parent/'share/xilinx/cells_sim.v'
    model=re.search(r'^module DSP48E1\b.*?^endmodule',library.read_text(),re.M|re.S).group(0)
    model=re.sub(r'\bspecify\b.*?\bendspecify\b','',model,flags=re.S)
    model_path=out/'dsp48e1.sv';model_path.write_text(model+'\n')
    reference=out/'reference.sv'
    reference.write_text('''module registered_sum_reference #(parameter p_width=48)(
        input logic clk,i_en,
        input logic signed [p_width-1:0] i_lhs,i_rhs,
        input logic i_carry,
        output logic signed [p_width-1:0] o_sum
    );
        always_ff @(posedge clk) begin
            if(i_en) o_sum<=i_lhs+i_rhs+p_width'(i_carry);
        end
    endmodule
    ''')
    summary={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'helper_sha256':hashlib.sha256(helper.encode()).hexdigest(),
        'primitive_library_sha256':hashlib.sha256(library.read_bytes()).hexdigest(),
        'clock_enable':'unconstrained each cycle','latency_enabled_edges':1,'runs':[]}
    for width in (1,17,36,48):
        for dsp in (0,1):
            lines=[]
            for label,top,path in [('reference','registered_sum_reference',reference),('candidate','requant_registered_sum',helper_path)]:
                lines += ['read_verilog -formal -sv -D VERIFIC '+str(path)+' '+str(model_path),
                          f'chparam -set p_width {width} '+(f'-set p_use_dsp {dsp} ' if label=='candidate' else '')+top,
                          'prep -top '+top+' -flatten','wreduce','opt -full','rename -top '+label,'design -stash '+label]
            lines+=['design -copy-from reference -as reference reference','design -copy-from candidate -as candidate candidate',
                    'equiv_make reference candidate equivalent','hierarchy -top equivalent',
                    'equiv_simple -seq 2','equiv_induct -seq 2','equiv_status -assert']
            stem=f'w{width}_dsp{dsp}';script=out/(stem+'.ys');script.write_text('\n'.join(lines)+'\n')
            with (out/(stem+'.log')).open('w') as stream:
                r=subprocess.run([sys.executable,__file__,'--out',str(out),'--worker',str(script)],stdout=stream,stderr=subprocess.STDOUT)
            text=(out/(stem+'.log')).read_text()
            passed=r.returncode==0 and 'Equivalence successfully proven' in text
            record={'width':width,'p_use_dsp':dsp,'passed':passed};summary['runs'].append(record);print(json.dumps(record),flush=True)
            if not passed:raise RuntimeError(text[-8000:])
    summary['passed']=all(r['passed'] for r in summary['runs'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
