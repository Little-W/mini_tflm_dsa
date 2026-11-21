#!/usr/bin/env python3
"""证明写回几何预计算在全部配置和握手输入下逐周期等价。"""
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


ADDRESS_INVARIANTS = """
    always_comb begin
        address_invariant = column_base_addr == row_group_base_addr_cur + col_offset_addr_cur;
        address_invariant &= {next_address_carry, next_address_low} ==
            {1'b0, next_address_base[ADDR_LOW_W-1:0]} +
            {1'b0, next_address_step[ADDR_LOW_W-1:0]};
        if (cfg_coalesce && !cfg_is_mode) begin
            address_invariant &= tile_base_addr_cur == column_base_addr;
        end
        if (state == S_WRITE) begin
            if (cfg_coalesce && !cfg_is_mode) begin
                address_invariant &= next_address_base ==
                    (co_has_next_col ? tile_base_addr_cur : row_group_base_addr_cur);
                address_invariant &= next_address_step ==
                    (co_has_next_col ? co_chunk_bytes : group_row_addr_step_cur);
            end else if (next_tile_row_advance_r) begin
                address_invariant &= next_address_base == tile_base_addr_cur;
                address_invariant &= next_address_step == row_addr_step_cur;
            end else if (next_tile_col_advance_r) begin
                address_invariant &= next_address_base == column_base_addr;
                address_invariant &= next_address_step == col_addr_step_cur;
            end else begin
                address_invariant &= next_address_base == row_group_base_addr_cur;
                address_invariant &= next_address_step == group_row_addr_step_cur;
            end
        end
    end
    always_comb assert(address_invariant);
"""


def instrument(content, top, registers, address):
    content = re.sub(r'\boa_writer\b', top, content)
    content = re.sub(r'output\s+logic\s+oa_calc_over\s*\n',
        'output logic oa_calc_over,\n'
        '    output logic [4095:0] formal_state,\n'
        '    output logic formal_invariant\n', content, count=1)
    observed = list(registers)
    observed.append("(cfg_lat_tick ? REG_WIDTH'(0) : group_row_addr_step_cur)")
    observed.extend(["((state == S_WRITE) ? next_address_base : REG_WIDTH'(0))",
                     "((state == S_WRITE) ? next_address_step : REG_WIDTH'(0))",
                     "((state == S_WRITE) ? next_address_low : ADDR_LOW_W'(0))",
                     "((state == S_WRITE) ? next_address_carry : 1'b0)"])
    if address:
        observed.extend(['co_initial_row_tiles_q', 'co_current_row_tiles_q',
            "((state == S_START || state == S_WRITE) ? co_next_row_tiles_q : 5'd0)"])
    else:
        observed.extend(["(cfg_is_mode ? 5'd1 : co_initial_row_tiles_q)",
            "(cfg_is_mode ? 5'd1 : co_current_row_tiles_q)",
            "((state == S_START || state == S_WRITE) ? (cfg_is_mode ? 5'd1 : co_next_row_tiles_q) : 5'd0)"])
    comparison = '    assign formal_state = {' + ', '.join(observed) + '};\n'
    additions = comparison + INVARIANTS + '\n    always_comb assert(formal_invariant);\n'
    if address:
        additions += '    logic address_invariant;\n' + ADDRESS_INVARIANTS
    if address and 'co_contiguous_q' in content:
        additions += """
    logic geometry_invariant;
    always_comb begin
        geometry_invariant = co_contiguous_q == (cfg_m == co_chunk_bytes);
        case (cfg_coalesce_cols)
            5'd16: geometry_invariant &= co_row_div_shift_q == 3'd0;
            5'd8: geometry_invariant &= co_row_div_shift_q == 3'd1;
            5'd4: geometry_invariant &= co_row_div_shift_q == 3'd2;
            5'd2: geometry_invariant &= co_row_div_shift_q == 3'd3;
            default: geometry_invariant &= co_row_div_shift_q == 3'd4;
        endcase
    end
    always_comb assert(geometry_invariant);
"""
    additions += """
    logic [REG_WIDTH-1:0] formal_group_step;
    always_comb begin
        case (cfg_ia_reuse_num)
            count_t'(1): formal_group_step = row_addr_step_cur;
            count_t'(2): formal_group_step = row_addr_step_cur << 1;
            count_t'(4): formal_group_step = row_addr_step_cur << 2;
            count_t'(8): formal_group_step = row_addr_step_cur << 3;
            count_t'(16): formal_group_step = row_addr_step_cur << 4;
            count_t'(25): formal_group_step = row_addr_step_cur * 5'd25;
            count_t'(32): formal_group_step = row_addr_step_cur << 5;
            count_t'(64): formal_group_step = row_addr_step_cur << 6;
            default: formal_group_step = row_addr_step_cur;
        endcase
    end
"""
    additions += ("    always_comb if (!cfg_lat_tick) assert(group_row_addr_step_cur == formal_group_step);\n"
                  if address else "    always_comb assert(group_row_addr_step_cur == formal_group_step);\n")
    return content.replace('endmodule', additions + '\nendmodule', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='9bb1e28a')
    parser.add_argument('--reference-rtl', type=Path)
    parser.add_argument('--rtl', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/oa_writer_geometry_formal')
    parser.add_argument('--profiles', nargs='+', default=[
        '4:32:4', '8:64:6', '16:32:7', '16:64:8', '16:64:16',
        '16:64:29', '16:64:32', '32:64:32',
        '4:32:4:4', '8:64:8:8', '8:64:9:9'])
    parser.add_argument('--max-steps', '--seq', type=int, default=8)
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = (args.reference_rtl.read_text() if args.reference_rtl else
                 read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True))
    current = args.rtl.read_text()
    registers = sorted(set(re.findall(r'\b(\w+)\s*<=', reference)) -
                       {'co_initial_row_tiles_q', 'co_current_row_tiles_q', 'co_next_row_tiles_q', 'group_row_addr_step_cur', 'next_address_base', 'next_address_step', 'next_address_low', 'next_address_carry'})
    original_file = out / 'reference.sv'
    original_file.write_text(instrument(reference, 'oa_writer_reference', registers, False))
    current_file = out / 'current.sv'
    current_file.write_text(instrument(current, 'oa_writer_current', registers, True))
    report = {'passed': True, 'reference': None if args.reference_rtl else args.reference,
              'reference_file': str(args.reference_rtl) if args.reference_rtl else None,
              'current_file': str(args.rtl),
              'source_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'input_value_constraints': None, 'handshake_constraints': None,
              'synthesis_define': args.synthesis,
              'all_public_outputs_compared_each_cycle': True,
              'state_comparison_scope': 'Common state each cycle; effective WS/IS row tiles; group step after configuration preparation; next row tiles when consumed',
              'profiles': []}
    for profile in args.profiles:
        values = list(map(int, profile.split(':')))
        lanes, bus, count = values[:3]
        register_width = values[3] if len(values) == 4 else 32
        label = f'n{lanes}_b{bus}_c{count}_r{register_width}'
        script = out / (label + '.ys')
        parameters = f'-GVLEN={lanes} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} -GREG_WIDTH={register_width}'
        if args.synthesis:
            parameters += ' -D SYNTHESIS=1'
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
               'register_width': register_width, 'passed': True,
               'common_state_signals': len(registers), **result}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
    if current != args.rtl.read_text():
        raise RuntimeError('验证期间 RTL 内容发生变化')
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
