#!/usr/bin/env python3
"""证明写回行分块寄存与截断乘积非零判断的完整输入关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OA = Path('rtl/npu/writeback/oa_writer.sv')
FIFO = Path('rtl/npu/writeback/vec_s8_to_fifo.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(folder, name, commands):
    script, log = folder / (name + '.ys'), folder / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=180)
    if result.returncode or 'SUCCESS' not in log.read_text():
        raise RuntimeError(log.read_text()[-8000:])
    return {'passed': True, 'log_sha256': digest(log)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='b7a2af3d')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    old = subprocess.check_output(['git', 'show', f'{args.reference}:{OA}'], cwd=ROOT, text=True)
    current = (ROOT / OA).read_text()
    registers = sorted(set(re.findall(r'\b(\w+)\s*<=', old)))
    relation = '''assign formal_invariant =
        co_initial_row_tiles_q == 5'((co_initial_rows + 9'd15) >> 4) &&
        co_current_row_tiles_q == 5'((co_current_rows + 9'd15) >> 4) &&
        co_next_row_tiles_q == 5'((co_next_rows_prepared + 9'd15) >> 4);'''
    sources = {}
    for label, content in [('reference', old), ('current', current)]:
        content = re.sub(r'\boa_writer\b', 'oa_' + label, content)
        content, count = re.subn(r'output\s+logic\s+oa_calc_over\s*\n',
                                'output logic oa_calc_over,\n'
                                'output logic [4095:0] formal_state,\n'
                                'output logic formal_invariant\n', content, count=1)
        if count != 1:
            raise ValueError('The writer output declaration differs')
        invariant = relation if label == 'current' else "assign formal_invariant = 1'b1;"
        content = content.replace('endmodule', 'assign formal_state = {' + ', '.join(registers) +
                                  '};\n' + invariant + '\nendmodule', 1)
        sources[label] = out / ('oa_' + label + '.sv')
        sources[label].write_text(content)
    summary = {'passed': False, 'reference': args.reference,
               'source_sha256': {str(p): digest(ROOT / p) for p in [OA, FIFO]},
               'writer_reference_sha256': hashlib.sha256(old.encode()).hexdigest(),
               'writer': [], 'truncated_product': []}
    for size, bus, width in [(4, 32, 8), (8, 64, 8), (16, 32, 16), (16, 64, 16),
                             (16, 64, 28), (16, 64, 32), (32, 64, 32)]:
        name = f'writer_n{size}_b{bus}_c{width}'
        commands = []
        for label in ('reference', 'current'):
            commands += [f'read_slang --top oa_{label} -GVLEN={size} -GBUS_WIDTH={bus} '
                         f'-GCOUNT_WIDTH={width} ' + shlex.quote(str(sources[label])),
                         f'prep -top oa_{label} -flatten', f'rename oa_{label} {label}',
                         f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten reference current miter', 'prep -top miter -flatten',
                     'sat -verify -prove trigger 0 -tempinduct -seq 1 -set-init-zero '
                     '-set-at 1 in_rst_n 0 -maxsteps 4']
        item = {'vlen': size, 'bus_width': bus, 'count_width': width,
                'compared_state_signals': len(registers), 'all_public_outputs_compared': True,
                'input_constraint': 'Reset is active at the first edge; all later inputs are unconstrained',
                **run(out, name, commands)}
        summary['writer'].append(item)
        print(json.dumps(item), flush=True)
    text = (ROOT / FIFO).read_text()
    start = text.index('  wire [BANK_COUNT_WIDTH-1:0] co_tiles =')
    end = text.index('  wire co_start =', start)
    fragment = text[start:end]
    helper = out / 'truncated_product.sv'
    helper.write_text('module truncated_product #(parameter BANK_COUNT_WIDTH=1) (\n'
                      'input [31:0] coalesce_rows, coalesce_cols, output equivalent);\n' +
                      fragment + '\nassign equivalent = (|co_nonzero_terms) == (co_tiles != 0);\nendmodule\n')
    for width in range(1, 13):
        item = {'retained_product_bits': width, 'arbitrary_input_bits': 64,
                **run(out, f'product_w{width}', [
                    f'read_slang --top truncated_product -GBANK_COUNT_WIDTH={width} ' +
                    shlex.quote(str(helper)), 'prep -top truncated_product -flatten',
                    'sat -verify -set-def-inputs -prove equivalent 1 -show-inputs'])}
        summary['truncated_product'].append(item)
        print(json.dumps(item), flush=True)
    if summary['source_sha256'] != {str(p): digest(ROOT / p) for p in [OA, FIFO]}:
        raise RuntimeError('The production sources changed during proof')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
