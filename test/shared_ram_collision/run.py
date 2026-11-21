#!/usr/bin/env python3
"""证明共享存储器 IA 端口碰撞判断的组合等价性。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/buffers/ia_ps_shared_ram.sv')
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


def collision_module(text, name):
    """提取实际优先级、地址选择、字节掩码与碰撞表达式。"""
    text = text[text.index('module ia_ps_channel_ram #('):]
    first = text.index('        assign read_port_one =')
    last = text.index('        assign ia_bank_read_en[bank]', first)
    body = text[first:last]
    # 写入数据不参与地址碰撞判断；对应地址与掩码赋值保持原文。
    body, count = re.subn(r'        assign ia_bank_write_data\[bank\] = [^;]*;\n', '', body)
    if count != 1:
        raise ValueError('未找到唯一的 IA 写数据选择表达式')
    comparisons = ''
    if 'ia_row_address_equal' in body:
        first = text.index('    for (genvar read_port = 0; read_port < 2; read_port++) begin : g_ia_row_compare')
        last = text.index('\n    for (genvar port_index', first)
        comparisons = text[first:last]
    return f'''module {name} #(parameter int W=9)(
    input logic [1:0] read_request, write_request,
    input logic [W-1:0] ia_read_row [2], ia_write_row [2],
    input logic [15:0] i_ia_write_mask [2],
    output logic collision
);
    localparam int bank=0;
    logic read_port_one, write_port_one;
    logic [W-1:0] ia_bank_read_addr [1], ia_bank_write_addr [1];
    logic [15:0] ia_bank_write_mask [1];
    logic [3:0] collision_terms;
    logic ia_row_address_equal [2][2];
{comparisons}
{body}
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='4dee27ffec4dc891daf2681379f8b3fd27fd41f2')
    parser.add_argument('--synthesize', action='store_true', help='对两份完整共享存储模块执行相同参数的综合')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    source = out / 'collision_miter.sv'
    source.write_text(collision_module(original, 'reference') +
                      collision_module(current, 'current') + '''
module collision_miter #(parameter int W=9)(
    input logic [1:0] read_request, write_request,
    input logic [W-1:0] ia_read_row [2], ia_write_row [2],
    input logic [15:0] i_ia_write_mask [2],
    output logic equal
);
    logic reference_collision, current_collision;
    reference #(.W(W)) u_reference(.*,.collision(reference_collision));
    current #(.W(W)) u_current(.*,.collision(current_collision));
    assign equal = reference_collision == current_collision;
endmodule
''')
    runs = []
    for width in (7, 8, 9):
        script = out / f'row{width}.ys'
        script.write_text(f'''read_slang --top collision_miter -GW={width} {shlex.quote(str(source))}
prep -top collision_miter -flatten
sat -verify -prove equal 1 -show-inputs -show-outputs
''')
        stage = run_stage(script, script.with_suffix('.log'), dict(os.environ))
        runs.append({'row_bits': width, 'passed': True, **stage})
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间共享存储器源码发生变化')
    result = {'passed': True, 'reference': args.reference,
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'input_constraints': None,
              'scope': '全部 IA 请求组合、行地址与字节掩码；保留端口零优先级',
              'runs': runs}
    if args.synthesize:
        cases = {}
        for label, text in (('reference', original), ('current', current)):
            path = out / f'{label}.sv'
            path.write_text(text)
            cases[label] = {
                'top': 'ia_ps_channel_ram',
                'options': ['-Gp_bank_bytes=8192', '-Gp_total_bytes=57344', '-Gp_shared_write_stage=1'],
                'sources': [str(path)],
                'configuration': '七个 8192 字节存储块，启用共享写数据寄存级',
            }
        case_file = out / 'synthesis_cases.json'
        case_file.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        with (out / 'synthesis.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--case-config', str(case_file), '--cases', 'reference', 'current',
                            '--out', str(out / 'synthesis')], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        measured = json.loads((out / 'synthesis/summary.json').read_text())
        keys = ('lut_cells', 'flip_flops', 'ramb36', 'ramb18', 'dsp',
                'longest_combinational_path_cells', 'longest_register_path_cells')
        result['synthesis'] = {'tool': measured['tool'], 'parameters': cases['current']['options'],
                              'resources': {label: {key: measured['cases'][label][key] for key in keys}
                                            for label in ('reference', 'current')}}
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('测量期间共享存储器源码发生变化')
    (out / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'proofs': len(runs)}))


if __name__ == '__main__':
    main()
