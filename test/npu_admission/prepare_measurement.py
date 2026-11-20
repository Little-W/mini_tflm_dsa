#!/usr/bin/env python3
"""提取实际配置接收表达式并建立输入与输出寄存器之间的映射测量。"""
import argparse
import json
from pathlib import Path
import subprocess

from run_formal import ROOT, TOP, FLAGS, admission, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='eaba7635')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    for label in ('reference', 'current'):
        source = ((ROOT/TOP).read_text() if label == 'current' else
                  subprocess.check_output(['git','show',f'{args.reference_rev}:{TOP}'],cwd=ROOT,text=True))
        path = out / (label + '.sv')
        connections = ','.join('.'+name+f'(flags_q[{i}])' for i,name in enumerate(FLAGS))
        wrapper = '''module admission_measure(input logic clk,
    input logic [14:0] i_flags, output logic [1:0] o_flags);
    logic [14:0] flags_q;
    logic [1:0] accepted;
    always_ff @(posedge clk) begin
        flags_q<=i_flags;
        o_flags<=accepted;
    end
    admission_logic u_admission('''+connections+''',.abort_state(flags_q[14:13]),
        .sa_ready(accepted[0]),.cfg_start_event(accepted[1]));
endmodule
'''
        path.write_text(admission(source, 'admission_logic') + wrapper)
        cases['admission_'+label]={'top':'admission_measure','options':['-DSYNTHESIS=1','-DXILINX_FPGA=1'],
            'parameters':{},'sources':[str(path)],'configuration':'实际配置接收表达式及寄存边界'}
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'source_sha256':{str(TOP):digest(ROOT/TOP)},
        'reference_rev':args.reference_rev,'input_bits':15,'output_bits':2,
        'source_files_sha256':{p.name:digest(p) for p in out.glob('*.sv')}},indent=2)+'\n')


if __name__ == '__main__':
    main()
