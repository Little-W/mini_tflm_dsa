#!/usr/bin/env python3
"""证明输出写回预计算在全部配置和握手输入下逐周期等价。"""
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
SOURCE = Path('rtl/npu/writeback/oa_writer.sv')
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from rtl_reference import read_rtl_source
from open_fpga_synth import run_stage


INVARIANTS = '''
    always_comb begin
        formal_invariant = 1'b1;
        if (state == S_REQ || state == S_START || state == S_WRITE) begin
            formal_invariant &= tile_row_inc_q == tile_row_inc;
            formal_invariant &= tile_col_inc_q == tile_col_inc;
            formal_invariant &= co_next_rows_remaining_q == co_next_rows_remaining;
            formal_invariant &= co_next_col_offset_q == col_offset_addr_cur + co_chunk_bytes;
        end
        if (state == S_START || state == S_WRITE) begin
            formal_invariant &= row_inc_in_range_q ==
                ((tile_row_inc < row_tiles_total) && (tile_row_inc < row_group_next_base_idx));
            formal_invariant &= col_inc_in_range_q == (tile_col_inc < col_tiles_total);
            formal_invariant &= group_inc_in_range_q == (row_group_next_base_idx < row_tiles_total);
            formal_invariant &= row_inc_is_last_q == (tile_row_inc == row_tiles_last_idx);
            formal_invariant &= col_inc_is_last_q == (tile_col_inc == col_tiles_last_idx);
            formal_invariant &= group_base_is_last_q == (row_group_base_idx == row_tiles_last_idx);
            formal_invariant &= group_next_is_last_q == (row_group_next_base_idx == row_tiles_last_idx);
        end
        if (state == S_WRITE) begin
            formal_invariant &= next_tile_row_r == next_tile_row_cur;
            formal_invariant &= next_tile_col_r == next_tile_col_cur;
            formal_invariant &= next_tile_row_is_last_r == next_tile_row_is_last_cur;
            formal_invariant &= next_tile_col_is_last_r == next_tile_col_is_last_cur;
            formal_invariant &= next_tile_wrap_r == next_tile_wrap_cur;
            formal_invariant &= next_tile_row_advance_r == next_tile_row_advance_cur;
            formal_invariant &= next_tile_col_advance_r == next_tile_col_advance_cur;
            formal_invariant &= next_tile_group_advance_r == next_tile_group_advance_cur;
            formal_invariant &= vec_valid_num_col_next_r == vec_valid_num_col_next_w[VCOL_W-1:0];
            formal_invariant &= vec_valid_num_row_next_r == vec_valid_num_row_next_w[VCOL_W-1:0];
        end
    end
'''


def instrument(content, top, registers, invariants):
    metadata = [name for name in registers if name.startswith('next_tile_') or
                name in ('vec_valid_num_col_next_r', 'vec_valid_num_row_next_r')]
    common = [name for name in registers if name not in metadata]
    content = re.sub(r'\boa_writer\b', top, content)
    content = re.sub(r'output\s+logic\s+oa_calc_over\s*\n',
        'output logic oa_calc_over,\n'
        '    output logic [4095:0] formal_state,\n'
        '    output logic formal_invariant\n', content, count=1)
    common_state = ', '.join(common)
    next_state = ', '.join(metadata)
    comparison = ('    assign formal_state = {' + common_state + ',\n'
                  "        ((state == S_WRITE) ? {" + next_state + "} : '0)};\n")
    content = content.replace('endmodule', comparison + invariants +
                              '\n    always_comb assert(formal_invariant);\nendmodule', 1)
    if top == 'oa_writer_current':
        for name in ('next_tile_row_r', 'next_tile_col_r'):
            content = re.sub(r'\b' + name + r'\b', name[:-2] + '_cur', content)
    return content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='8b46373c')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/oa_writer_formal')
    parser.add_argument('--profiles', nargs='+', default=[
        '4:32:4', '8:64:6', '16:32:7', '16:64:8', '16:64:16',
        '16:64:29', '16:64:32', '32:64:32'])
    parser.add_argument('--max-steps', '--seq', type=int, default=8)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    current = (ROOT / SOURCE).read_text()
    reference_registers = set(re.findall(r'\b(\w+)\s*<=', reference))
    current_registers = set(re.findall(r'\b(\w+)\s*<=', current))
    registers = sorted(reference_registers & current_registers)
    original_file = out / 'reference.sv'
    reference_checks = INVARIANTS[INVARIANTS.index('        if (state == S_WRITE) begin'):]
    reference_checks = reference_checks.replace('if (state == S_WRITE)',
                                                 'if (state == S_START || state == S_WRITE)', 1)
    reference_checks = "    always_comb begin\n        formal_invariant = 1'b1;\n" + reference_checks
    original_file.write_text(instrument(reference, 'oa_writer_reference', registers, reference_checks))
    current_file = out / 'current.sv'
    current_file.write_text(instrument(current, 'oa_writer_current', registers, INVARIANTS))
    report = {'passed': True, 'reference': args.reference,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'input_value_constraints': None, 'handshake_constraints': None,
              'all_public_outputs_compared_each_cycle': True,
              'metadata_comparison_state': 'S_WRITE', 'profiles': []}
    for profile in args.profiles:
        lanes, bus, count = map(int, profile.split(':'))
        label = f'n{lanes}_b{bus}_c{count}'
        script = out / (label + '.ys')
        parameters = f'-GVLEN={lanes} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count}'
        script.write_text(
            f'read_slang --top oa_writer_reference {parameters} {shlex.quote(str(original_file))}\n'
            'prep -top oa_writer_reference -flatten\nrename oa_writer_reference gold\n'
            'design -stash gold\n'
            f'read_slang --top oa_writer_current {parameters} {shlex.quote(str(current_file))}\n'
            'prep -top oa_writer_current -flatten\nrename oa_writer_current gate\n'
            'design -copy-from gold -as gold gold\n'
            'miter -equiv -flatten gold gate miter\nprep -top miter -flatten\nchformal -lower\nopt -full\n'
            'sat -verify -prove trigger 0 -prove-asserts -tempinduct -seq 1 -set-init-zero '
            f'-set-at 1 in_rst_n 0 -maxsteps {args.max_steps}\n')
        result = run_stage(script, script.with_suffix('.log'), dict(os.environ))
        row = {'vlen': lanes, 'bus_width': bus, 'count_width': count,
               'passed': True, 'common_state_signals': len(registers), **result}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    if current != (ROOT / SOURCE).read_text():
        raise RuntimeError('验证期间 RTL 内容发生变化')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
