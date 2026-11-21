#!/usr/bin/env python3
"""证明流式地址选择、窗口核编号及历史坐标的组合变换。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    address = text[text.index('  assign address_stream_write ='):text.index('  always_ff', text.index('  assign address_stream_write ='))]
    range_start = text.index('  assign range_update_select[0] =')
    range_logic = text[range_start:text.index('  always_ff', range_start)]
    active_start = text.index('  assign active_update_select[0] =')
    active_stop = re.search(r'^  always_ff', text[active_start:], re.M).start() + active_start
    active_logic = text[active_start:active_stop]
    active_logic = re.sub(r'^    always_ff .*?^    end\n', '', active_logic, flags=re.M | re.S)
    has_column_update = 'assign column_update_candidate[0]' in active_logic
    column_reset = re.search(r'if \(!rst_n\) column_lane_allowed_q\[lane\] <= (.*?);', text)
    reset_logic = ''
    if has_column_update:
        if column_reset is None:
            raise RuntimeError('Column range reset expression is missing')
        reset_logic = '''
    logic [TILE_COUNT_W-1:0] reset_column_count;
    logic [LANES:0] column_reset_value, reference_column_reset;
    assign reset_column_count=TILE_COUNT_W'(SIZE);
    for (genvar lane=0;lane<=LANES;lane++) begin : g_column_reset
        assign column_reset_value[lane]=''' + column_reset[1] + ''';
        assign reference_column_reset[lane]=TILE_COUNT_W'(lane)<reset_column_count;
    end
'''
    remaining = text[text.index('  if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_stream_remaining'):text.index('  assign stream_context=')]
    window = text[text.index('  for (genvar target = 0; target < 3; target++) begin : g_window_tap_target'):text.index('  // 空间分块起点保留三十二位模加结果')]
    window = window.replace('window_tap_target_q[target]', 'window_tap_target[target]')
    boundary_start = text.index('      logic boundary_s8, boundary_s16;')
    boundary_end = text.index('      assign match_i_b', boundary_start)
    boundary = text[boundary_start:boundary_end]
    crossing_start = text.index('    for (genvar lane = 0; lane < LANES; lane++) begin : g_crossing_lane')
    crossing_end = text.index('    assign next_byte_saved_hit', crossing_start)
    crossing = text[crossing_start:crossing_end]
    history = '\n'.join(re.search(pattern, text, re.S)[0] for pattern in (
        r'  assign history_reduce_i_a = .*?;', r'  assign history_reduce_generate = .*?;',
        r'  assign \{unused_history_reduce_high, history_reduce_i_b\} = .*?;',
        r'  assign history_reduce_full_sum = .*?;'))
    proof = out / 'address.sv'
    proof.write_text('''module frontend_address_proof #(
    parameter int SIZE = 16,
    parameter int LANES = 8
) (
    input logic [4:0] state_index,
    input logic cfg_valid, cfg_ready, tile_commit,
    input logic commit_invalid, commit_fast, wr_ready, cache_rsp_valid, cache_rsp_error,
    input logic chunk_reaches_end, past_active_q, row_last_q, row_base_valid, geometry_tile,
    input logic coordinate_address_valid, current_coordinate_valid, tap_wrap, pad_q,
    input logic ix_step_below_limit, group_end_o_equal, input_s16,
    input logic [$clog2(SIZE+1)-1:0] col_remaining, active_remaining,
    input logic [LANES-1:0] chunk_lane_allowed,
    input logic [31:0] addr, commit_address, next_row_addr, next_tap_addr, next_byte_addr, channel_addr,
    input logic [31:0] q0, tile_q0,
    input logic [15:0] group_c, input_c, group_offset, dilation_w,
    input logic [15:0] last_x, p_delta, output_w,
    input logic range_decode_write, range_stream_allowed,
    input logic [8:0] range_decode_value, group_range_cfg, commit_channel_range, group_range_stream_value, group_range_q,
    input logic [$clog2(SIZE+1)-1:0] commit_active_columns, active_cols_q,
    input logic [$clog2(SIZE+1)-1:0] commit_columns, cols_q,
    output logic equivalent
);
    localparam int TILE_COUNT_W = $clog2(SIZE+1), CHUNK_COUNT_W = $clog2(LANES+1);
    localparam logic [21:0] ADDRESS_CHANNEL=22'h020000, WAIT_WORD=22'h080000,
        STREAM=22'h100000, ZERO_STREAM=22'h200000;
    logic [21:0] state;
    typedef struct packed { logic [15:0] group_c, input_c, group_offset, dilation_w, output_w; logic input_s16; } cfg_t;
    cfg_t c;
    typedef struct packed {
        logic invalid, fast;
        logic [31:0] address;
        logic [8:0] channel_range;
        logic [TILE_COUNT_W-1:0] active_columns;
        logic [TILE_COUNT_W-1:0] columns;
    } commit_t;
    commit_t committing_tile;
    localparam int p_saved_group_lanes=8;
    logic [3:0] range_update_select;
    logic [8:0] range_update_value, reference_range, candidate_range;
    logic [2:0] active_update_select;
    logic [2:0][TILE_COUNT_W-1:0] active_update_candidate;
    logic [TILE_COUNT_W-1:0] active_update_value, candidate_active, reference_active;
    logic [LANES:0] active_lane_allowed_q, active_lane_update, reference_active_lanes;
    logic [LANES:0] column_lane_allowed_q, column_lane_update, reference_column_lanes;
    logic [LANES:0] chunk_selected;
    logic [2:0][TILE_COUNT_W-1:0] column_update_candidate;
    logic [TILE_COUNT_W-1:0] column_update_value, reference_columns;
    logic [4:0] address_update_select;
    logic [31:0] address_update_value, reference_address, candidate_address;
    logic address_stream_write, address_column_advance, address_linear_tap;
    logic wr_valid, column_after_chunk, active_after_chunk;
    logic [CHUNK_COUNT_W-1:0] chunk_count;
    logic [2:0][32:0] window_tap_target;
    logic [2:0] unused_window_tap_carry;
    logic [3:0] incoming_tap_match_o_equal;
    logic [32:0] forward_sum, backward_sum, previous_sum;
    logic [17:0] history_reduce_i_a, history_reduce_i_b, history_reduce_generate;
    logic [18:0] history_reduce_full_sum;
    logic unused_history_reduce_high;
    logic [17:0] history_reference;
    localparam int p_word_shift=3, p_cache_read_bytes=8;
    logic [LANES:0] step_word_boundary;
    logic [LANES-1:0] crossing_lane;
    logic word_boundary;
    logic [5:0] reference_word_offset;
    assign state = 22'b1 << state_index;
    assign c = {group_c, input_c, group_offset, dilation_w, output_w, input_s16};
    assign committing_tile = {commit_invalid, commit_fast, commit_address, commit_channel_range,
                              commit_active_columns, commit_columns};
    assign wr_valid = state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)] ||
        (state[$clog2(WAIT_WORD)] && cache_rsp_valid && !cache_rsp_error);
    always_comb begin
        chunk_count = '0;
        for (int lane=0; lane<LANES; lane++)
            if (chunk_lane_allowed[lane]) chunk_count = CHUNK_COUNT_W'(lane+1);
    end
''' + remaining + address + range_logic + active_logic + reset_logic + window + history + '\n    for (genvar step=0; step<=LANES; step++) begin : g_boundary\n' + boundary + '\n    end\n' + crossing + '''
    for (genvar lane=0;lane<=LANES;lane++) begin : g_active_invariant
        assign active_lane_allowed_q[lane] = TILE_COUNT_W'(lane) < active_remaining;
        assign column_lane_allowed_q[lane] = TILE_COUNT_W'(lane) < col_remaining;
        assign reference_active_lanes[lane] = TILE_COUNT_W'(lane) < reference_active;
        assign reference_column_lanes[lane] = TILE_COUNT_W'(lane) < reference_columns;
        assign chunk_selected[lane] = chunk_count == CHUNK_COUNT_W'(lane);
    end
    always_comb begin
        reference_range = group_range_q;
        if (range_decode_write) reference_range = range_decode_value;
        else if (cfg_valid && cfg_ready) reference_range = group_range_cfg;
        else if (tile_commit) begin
            if (!commit_invalid && commit_fast) reference_range = commit_channel_range;
        end else if (wr_valid && range_stream_allowed) reference_range = group_range_stream_value;
        reference_active = active_remaining;
        reference_columns = col_remaining;
        if (!(cfg_valid && cfg_ready)) begin
            if (tile_commit) begin
                if (!commit_invalid) begin
                    reference_active = commit_active_columns;
                    reference_columns = commit_columns;
                end
            end else if (wr_valid && wr_ready) begin
                if (chunk_reaches_end) begin
                    if (!row_last_q) begin
                        reference_active = active_cols_q;
                        reference_columns = cols_q;
                    end
                end else begin
                    reference_active = active_remaining - TILE_COUNT_W'(chunk_count);
                    reference_columns = col_remaining - TILE_COUNT_W'(chunk_count);
                end
            end
        end
    end
    assign candidate_range = |range_update_select ? range_update_value : group_range_q;
    assign candidate_active = |active_update_select ? active_update_value : active_remaining;
    always_comb begin
        reference_address = addr;
        if (cfg_valid && cfg_ready) begin
        end else if (tile_commit) begin
            if (!commit_invalid && commit_fast) reference_address = commit_address;
        end else if (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) begin
            if (state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) begin
            end else if (wr_valid && wr_ready) begin
                if (chunk_reaches_end) begin
                    if (!row_last_q && row_base_valid && !geometry_tile) reference_address = next_row_addr;
                end else if (!(past_active_q || TILE_COUNT_W'(chunk_count) >= active_remaining)) begin
                    if (group_end_o_equal) begin
                        if (coordinate_address_valid) reference_address = next_tap_addr;
                        else if (!current_coordinate_valid && !tap_wrap && !pad_q &&
                                 group_c == input_c && group_offset == 16'd0 && dilation_w == 16'd1 &&
                                 ix_step_below_limit) reference_address = next_byte_addr;
                    end else reference_address = next_byte_addr;
                end
            end
        end
        if (state[$clog2(ADDRESS_CHANNEL)]) reference_address = channel_addr;
    end
    assign candidate_address = |address_update_select ? address_update_value : addr;
    assign forward_sum = {1'b0, q0} + {17'd0, group_c};
    assign backward_sum = {1'b0, tile_q0} + {17'd0, group_c};
    assign previous_sum = {1'b0, tile_q0} + {16'd0, group_c, 1'b0};
    assign history_reference = {2'b0, last_x} + {2'b0, p_delta} - {2'b0, output_w};
    assign reference_word_offset = {3'd0, addr[2:0]} +
        (input_s16 ? (6'(chunk_count) << 1) : 6'(chunk_count));
    assign equivalent = candidate_address == reference_address &&
        candidate_range == reference_range && candidate_active == reference_active &&
        (!(|active_update_select) || active_lane_update == reference_active_lanes) &&
''' + ('''        (!(|active_update_select) || (column_lane_update == reference_column_lanes &&
            column_update_value == reference_columns)) &&
        column_reset_value == reference_column_reset &&
''' if has_column_update else '') + '''
        word_boundary == (reference_word_offset >= 6'd8) &&
        incoming_tap_match_o_equal[1] == (forward_sum == {1'b0, tile_q0}) &&
        incoming_tap_match_o_equal[2] == (backward_sum == {1'b0, q0}) &&
        incoming_tap_match_o_equal[3] == (previous_sum == {1'b0, q0}) &&
        history_reduce_full_sum[17:0] == history_reference;
endmodule
''')
    prefix = out / 'parallel_prefix_add.sv'
    prefix.write_bytes((root / 'rtl/common/parallel_prefix_add.sv').read_bytes())
    summary = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'proof_sha256': hashlib.sha256(proof.read_bytes()).hexdigest(),
               'input_constraints': [], 'state_encoding': 'one-hot value selected by an unconstrained five-bit index',
               'column_range_reset_checked': has_column_update,
               'runs': []}
    for size, fpga in ((size, fpga) for size in (4, 16) for fpga in (0, 1)):
        script, log = out / f's{size}_f{fpga}.ys', out / f's{size}_f{fpga}.log'
        script.write_text('read_slang --top frontend_address_proof -GSIZE=' + str(size) + ' ' +
                          ('-D XILINX_FPGA=1 ' if fpga else '') + shlex.join(map(str, (prefix, proof))) + '\n' +
                          'prep -top frontend_address_proof -flatten\ncheck -assert\n' +
                          'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                           stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('Address comparison did not complete')
        summary['runs'].append({'SIZE': size, 'LANES': 8, 'xilinx_fpga': bool(fpga), 'passed': True,
                                'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(f'FRONTEND_ADDRESS_FORMAL_PASS size={size} fpga={fpga}', flush=True)
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
