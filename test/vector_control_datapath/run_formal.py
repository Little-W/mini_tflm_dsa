#!/usr/bin/env python3
"""证明实际位置递增和串行读取，并记录寄存值消费检查的位置。"""
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
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fragment(source, name, tile):
    state_type = re.search(r'typedef enum logic \[5:0\].*?state_t;', source, re.S)[0]
    first = source.index('  logic [TILE_INDEX_W-1:0] serial_acc_read_index;')
    last = source.index('  logic signed [31:0] reduce_alu_i_lhs', first)
    read_logic = source[first:last]
    if '  logic [31:0] position_next;' in source:
        first = source.index('  logic [31:0] position_next;')
        last = source.index('  // 有效通道数', first)
        position_logic = source[first:last]
    else:
        position_logic = "logic [31:0] position_next; assign position_next = position + 32'd1;"
    return f'''module {name} #(
    parameter int TILE={tile}, TILE_INDEX_W=(TILE<=1)?1:$clog2(TILE)
) (
    input logic [5:0] state,
    input logic [31:0] position,
    input logic signed [31:0] acc_buf[TILE],
    input logic [TILE_INDEX_W-1:0] quant_index, q_issue, reduce_index,
    input logic [7:0] soft_exp_index,
    input logic softmax_s8,
    output logic [31:0] next_position, serial_value,
    output logic [TILE_INDEX_W-1:0] serial_index
);
    {state_type}
    {read_logic}
    {position_logic}
    assign next_position = position_next;
    assign serial_index = serial_acc_read_index;
    assign serial_value = serial_acc_read_index < TILE ? serial_acc_read_data : 32'd0;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--reference', default='dde5e7c9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    hashes = {str(path): digest(ROOT / path) for path in (SOURCE, HELPER)}
    report = {
        'passed': False, 'reference': args.reference,
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'source_sha256': hashes, 'inputs_constrained': False,
        'scope': 'Complete 32-bit position increment; serial read address in every state and every in-range read.',
        'registered_consumer_checks': {
            'observer': 'test/monitors/vector_engine_observer.sv:vector_control_datapath_observer',
            'method': 'Assertions on actual engine state, capture values, and consumed values during numerical regression',
            'properties': ['parameter descriptors after CHECK', 'saved Softmax request index',
                           'next-window qualification at EXECUTE_COMMIT',
                           'saved channel-group completion at EXECUTE_COMMIT',
                           'prefetched accumulator value and no accumulator writes during reduction'],
        },
        'runs': [],
    }
    for tile in (1, 3, 4, 8, 16, 32, 64):
        folder = out / f'tile{tile}'
        folder.mkdir(exist_ok=True)
        commands = []
        for name, source in (('reference', reference), ('candidate', current)):
            path = folder / f'{name}.sv'
            path.write_text(fragment(source, name, tile))
            commands += [
                f'read_slang --top {name} ' + shlex.join(map(str, [path, ROOT / HELPER])),
                f'prep -top {name} -flatten', 'memory_map', 'opt -full',
                f'design -stash {name}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from candidate -as candidate candidate',
            'equiv_make reference candidate comparison', 'hierarchy -top comparison',
            'equiv_simple', 'equiv_status -assert',
        ]
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py',
                                     '--worker', script], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120)
        text = log.read_text()
        row = dict(tile=tile, passed=result.returncode == 0 and 'Equivalence successfully proven' in text,
                   script_sha256=digest(script), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'位置和读取关系证明未完成：{log}')
    if hashes != {str(path): digest(ROOT / path) for path in (SOURCE, HELPER)}:
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
