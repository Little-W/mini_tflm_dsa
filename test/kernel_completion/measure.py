#!/usr/bin/env python3
"""测量权重加载完成条件和完整控制模块的组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/kernel_loader_ctrl.sv'
sys.path.insert(0, str(ROOT/'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='1d809964')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''// 完成资格的寄存输入和输出测量模块。
module measure(
    input logic clk, // 测量时钟
    input logic [8:0] value, // 两个待处理数量及发出计数和完成条件
    output logic complete // 寄存后的任务完成资格
);
logic [8:0] q;
logic result,expected;
always_ff @(posedge clk) begin q<=value; complete<=result; end
wire [1:0] pending_loads=q[1:0],pending_sends=q[3:2];
wire issued_zero=q[4],issued_one=q[5],all_done=q[6],all_issued=q[7],load_done=q[8];
'''
    body = runpy.run_path(str(Path(__file__).with_name('run.py')))['REFERENCE_BODY']
    (out/'reference.sv').write_text(header+body+'assign result=expected;\nendmodule\n')
    (out/'current.sv').write_text(header+'''kernel_completion_check dut(
    .i_pending_loads(pending_loads),.i_pending_sends(pending_sends),
    .i_issued_zero(issued_zero),.i_issued_one(issued_one),.i_all_loads_done(all_done),
    .i_all_loads_issued(all_issued),.i_load_done(load_done),.o_complete(result));
endmodule
''')
    (out/'control_reference.sv').write_bytes(subprocess.check_output(['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    (out/'control_current.sv').write_bytes((ROOT/SOURCE).read_bytes())
    cases = {}
    for name in ('reference', 'current', 'control_reference', 'control_current'):
        control = name.startswith('control_')
        cases[name] = {'top': 'kernel_loader_ctrl' if control else 'measure',
            'sources': [str(out/(name+'.sv'))],
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']+
                       (['-GSIZE=16', '-GCOUNT_WIDTH=29'] if control else []),
            'configuration': '完整权重加载控制' if control else '有界计数的发送完成条件'}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', config, '--cases', *cases, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name, case in cases.items():
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        records[name] = {key: json.loads((cost/(key+'.json')).read_text())
                        for key in ('manifest', 'summary')}
        if case['top'] == 'measure':
            module = json.loads((cost/'mapped.json').read_text())['modules']['measure']
            for cell, origin in register_origins(source/'pre_lut.il', 'measure').items():
                if cell in module['cells']:
                    module['cells'][cell].setdefault('attributes', {})['fpga_register_origin'] = origin
            records[name]['load_done_paths'] = connected_paths(module,
                root_filter=lambda n, c, p: c.get('attributes', {}).get('fpga_register_origin') == 'q [8]',
                limit=1, group_limit=0)
    (out/'measurement.json').write_text(json.dumps({'cases': records}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
