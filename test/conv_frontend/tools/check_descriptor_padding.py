#!/usr/bin/env python3
"""证明提交坐标的共享边界检查与全部描述符候选的独立检查等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
RELATIVE = 'rtl/npu/conv/conv_im2col_frontend.sv'


def section(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def assignment(text, name):
    return re.search(r'  assign ' + re.escape(name) + r'\s*=.*?;', text, re.S)[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    candidate = (root / RELATIVE).read_text()
    reference = (args.reference_root.resolve() / RELATIVE).read_text()
    bounds = section(reference, '  assign bound_a[0]', '  // 数据字匹配比较')
    candidates = section(reference, '  logic [6:0][COORD_W-1:0] candidate_coordinate_i_a',
                         '  logic incoming_kx_last;')
    padding_names = ('incoming_base_padding', 'incoming_step_padding', 'incoming_wrap_padding',
        'window_forward_padding', 'window_backward_padding', 'window_previous_padding',
        'incoming_skip_padding', 'prepared_padding_value')
    reference_padding = '\n'.join(assignment(reference, name) for name in padding_names)
    select = section(reference, '  always_comb begin\n    prepared_padding_select',
                     '  // 描述符寄存级保存已选择')
    coordinates = section(candidate, '  always_comb begin\n    prepared_coordinate_x',
                          '  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_bound')
    commit_bounds = section(candidate,
        '  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_bound',
        '  // 已保存窗口保留原填充标志')
    formula = re.search(r'      committing_tile.padding = .*?;', candidate, re.S)[0]
    formula = formula.replace('committing_tile.padding', 'candidate_padding')
    proof = out / 'padding.sv'
    proof.write_text('''module descriptor_padding_proof (
    input logic signed [34:0] row_base_ix, row_base_iy, window_next_ix, window_next_iy, tap_pair_dx,
    input logic signed [32:0] row_wrap_dx, tap_wrap_dx,
    input logic [15:0] input_w, input_h, dilation_w, dilation_h, stride_w, stride_h, kx0_q,
    input logic row_wrap, incoming_next_position_eligible, incoming_position_same_tap,
    input logic incoming_position_previous_row, incoming_position_forward_tap,
    input logic incoming_position_backward_tap, incoming_next_tile_fast, incoming_skip_tap,
    input logic incoming_q_equal, incoming_tap_wrap, window_next_padding,
    output logic equivalent
);
    localparam int COORD_W=35;
    localparam bit REGISTER_DESCRIPTOR=1;
    typedef struct packed {logic [15:0] input_w,input_h,dilation_w,dilation_h,stride_w,stride_h;} cfg_t;
    cfg_t c;
    assign c={input_w,input_h,dilation_w,dilation_h,stride_w,stride_h};
    // 快速位置选择包含至少一种已保存的核位置匹配，其他资格条件独立变化。
    wire incoming_next_position_fast = incoming_next_position_eligible &&
        (incoming_position_same_tap || incoming_position_previous_row ||
         incoming_position_forward_tap || incoming_position_backward_tap);
    wire [34:0] ix='0, iy='0;
    wire tap_wrap=1'b0;
    logic [34:0] bound_a[7], bound_b[7], bound_sum[7];
    logic [15:0] bound_limit[7];
    logic [6:0] bound_valid;
    logic incoming_base_padding, incoming_step_padding, incoming_wrap_padding;
    logic window_forward_padding, window_backward_padding, window_previous_padding;
    logic incoming_skip_padding, next_row_padding;
    logic [8:0] prepared_padding_select, prepared_padding_value;
    logic [9:0] prepared_word_select;
    logic [34:0] prepared_coordinate_x, prepared_coordinate_y;
    logic [34:0] prepared_coordinate_dx, prepared_coordinate_dy;
    logic [1:0] prepared_coordinate_carry;
    logic [1:0][34:0] committing_coordinate;
    logic [1:0] unused_committing_coordinate_carry, committing_coordinate_valid;
    logic reference_padding, candidate_padding;
    typedef struct packed {
        logic [34:0] input_x,input_y,coordinate_dx,coordinate_dy;
        logic coordinate_x_carry, coordinate_y_carry;
        logic [8:0] padding_select,padding_value;
    } prepared_t;
    prepared_t prepared_tile_q;
    assign prepared_tile_q={prepared_coordinate_x,prepared_coordinate_y,
        prepared_coordinate_dx,prepared_coordinate_dy,prepared_coordinate_carry[0],
        prepared_coordinate_carry[1],prepared_padding_select,prepared_padding_value};
    assign next_row_padding=!bound_valid[0] || !bound_valid[1];
''' + bounds + candidates + reference_padding + '\n' + select + coordinates + commit_bounds + '''
    assign reference_padding=|(prepared_padding_select & prepared_padding_value);
    always_comb begin
''' + formula + '''
    end
    assign equivalent=reference_padding==candidate_padding;
endmodule
''')
    sources = [root / 'rtl/common' / name for name in
               ('add_equal.sv', 'parallel_prefix_add.sv', 'unsigned_compare.sv')]
    summary = dict(source_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
        reference_sha256=hashlib.sha256(reference.encode()).hexdigest(),
        proof_sha256=hashlib.sha256(proof.read_bytes()).hexdigest(), inputs_constrained=False,
        stored_context_invariant='configuration remains unchanged while a descriptor is prepared',
        selector_invariant='a fast saved position requires at least one matching kernel position', runs=[])
    for fpga in (0, 1):
        script, log = out / f'fpga{fpga}.ys', out / f'fpga{fpga}.log'
        script.write_text('read_slang --top descriptor_padding_proof ' +
            ('-DXILINX_FPGA=1 ' if fpga else '') + shlex.join(map(str, [*sources, proof])) + '\n' +
            'prep -top descriptor_padding_proof -flatten\ncheck -assert\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        assert 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        summary['runs'].append(dict(fpga=bool(fpga), passed=True))
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print('DESCRIPTOR_PADDING_PASS', out / 'summary.json')


if __name__ == '__main__':
    main()
