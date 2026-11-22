#!/usr/bin/env python3
"""提取实际配置接收表达式并建立输入与输出寄存器之间的映射测量。"""
import argparse
import json
from pathlib import Path

from run_formal import (ROOT, TOP, CURRENT_FLAGS, current_admission,
                        admission_specification, condition_module, digest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    input_width = len(CURRENT_FLAGS) + 2
    source = (source_root/TOP).read_text()
    source_hash = digest(source_root / TOP)
    for label in ('reference', 'current'):
        path = out / (label + '.sv')
        connections = ','.join('.'+name+f'(flags_q[{i}])' for i,name in enumerate(CURRENT_FLAGS))
        wrapper = f'''module admission_measure(input logic clk,
    input logic [{input_width-1}:0] i_flags, output logic [1:0] o_flags);
    logic [{input_width-1}:0] flags_q;
    logic [1:0] accepted;
    always_ff @(posedge clk) begin
        flags_q<=i_flags;
        o_flags<=accepted;
    end
    admission_logic u_admission('''+connections+f''',.abort_state(flags_q[{input_width-1}:{input_width-2}]),
        .accept_conditions(accepted[0]),.matrix_start_candidate(accepted[1]));
endmodule
'''
        implementation = (current_admission(source, 'admission_logic') if label == 'current'
                          else admission_specification('admission_logic'))
        path.write_text(condition_module(implementation) + wrapper)
        cases['admission_'+label]={'top':'admission_measure','options':['-DSYNTHESIS=1'],
            'parameters':{},'sources':[str(path)],'configuration':'寄存前组合接收资格；输入输出测量寄存器'}
    if digest(source_root / TOP) != source_hash:
        raise RuntimeError('Admission source changed during extraction')
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'source_sha256':{str(TOP):source_hash},
        'reference':'current combinational task acceptance specification','input_bits':input_width,'output_bits':2,
        'flags':list(CURRENT_FLAGS),
        'outputs':['task_accept_conditions','matrix_start_candidate'],
        'top_level_ready_register_included':False,
        'source_files_sha256':{p.name:digest(p) for p in out.glob('*.sv')}},indent=2)+'\n')


if __name__ == '__main__':
    main()
