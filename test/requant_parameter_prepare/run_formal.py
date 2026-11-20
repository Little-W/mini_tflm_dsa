#!/usr/bin/env python3
"""验证量化参数准备函数与真实配置保存行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_requant.sv')
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
sys.path.insert(0, str(ROOT / 'test'))
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def full_module(source):
    return source.split('module vec_requant_full #(', 1)[1].split('\nendmodule', 1)[0]


def functions(source):
    return '\n'.join(re.search(r'  function automatic [^\n]*\b' + name +
                               r'\(.*?  endfunction', source, re.S).group()
                     for name in ('prepare_multiplier', 'prepare_amount'))


def function_unit(source, name):
    return f'''module {name} #(parameter bit ENABLE_S16 = 1) (
    input logic signed [31:0] multiplier_in, shift_in,
    input logic cfg_s16,
    output logic [38:0] result
);
''' + functions(source) + '''
    assign result = {prepare_multiplier(multiplier_in, cfg_s16),
                     prepare_amount(shift_in, cfg_s16)};
endmodule
'''


def configuration_unit(source, name):
    first = source.index('  logic s16_mode;')
    mode = source[first:source.index('  localparam int BYTES_PER_WORD', first)]
    first = source.index('  always_ff @(posedge clk)', source.index('  logic signed [31:0] pt_multiplier_r;'))
    block = source[first:source.index('  // compute number of tiles', first)]
    kept = []
    for line in block.splitlines():
        text = line.strip()
        if text.startswith(('always_ff', 'if ', 'end')) or re.match(r'pt_\w+\s*<=', text):
            kept.append(line)
    assignments = '\n'.join(re.findall(r'^  assign pt_product_\w+\s*=.*?;', source, re.M | re.S))
    return f'''module {name} #(parameter bit ENABLE_S16 = 1) (
    input logic clk, rst_n, init_cfg, cfg_s16,
    input logic signed [31:0] multiplier_in, shift_in,
    output logic [103:0] result
);
    logic signed [31:0] pt_multiplier_r, pt_shift_r, pt_product_multiplier_r;
    logic [6:0] pt_product_amount_r;
''' + functions(source) + mode + assignments + '\n' + '\n'.join(kept) + '''
    assign result = {s16_mode, pt_multiplier_r, pt_shift_r,
                     pt_product_multiplier_r, pt_product_amount_r};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    units = {'reference': full_module(original), 'current': full_module(current)}
    report = {'passed': True, 'reference': args.reference,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'input_value_constraints': None, 'runs': []}
    for check, builder in (('functions', function_unit), ('configuration', configuration_unit)):
        sources = {}
        for name, unit in units.items():
            sources[name] = out / f'{check}_{name}.sv'
            sources[name].write_text(builder(unit, name))
        for enabled in (0, 1):
            label = f'{check}_s16_{enabled}'
            script = out / (label + '.ys')
            commands = []
            for name in units:
                commands += [f'read_slang --top {name} -GENABLE_S16={enabled} '
                             + shlex.quote(str(sources[name])),
                             f'prep -top {name} -flatten', 'opt -full',
                             f'design -stash {name}']
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current']
            if check == 'functions':
                commands += ['miter -equiv -flatten reference current proof',
                             'prep -top proof -flatten', 'opt -full',
                             'sat -verify -prove trigger 0 -set-def-inputs']
            else:
                commands += ['equiv_make reference current proof', 'hierarchy -top proof',
                             'equiv_simple -seq 2', 'equiv_induct -seq 3',
                             'equiv_status -assert']
            script.write_text('\n'.join(commands) + '\n')
            result = run_stage(script, script.with_suffix('.log'), dict(os.environ))
            row = {'check': check, 'enable_s16': enabled, 'passed': True,
                   'compared_output_bits': 39 if check == 'functions' else 104,
                   'arbitrary_init_and_reset': check == 'configuration', **result}
            report['runs'].append(row)
            print(json.dumps(row), flush=True)
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间 RTL 内容发生变化')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
