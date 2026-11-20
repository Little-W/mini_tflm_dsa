#!/usr/bin/env python3
"""从实际 NPU 顶层提取偏置组的全部状态与行索引逻辑。"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')


def control_region(source):
    start = source.index('        logic [REG_WIDTH-1:0] is_bias_group_base;')
    end = source.index('\n    genvar rq_i;', start)
    region = source[start:end]
    removed = re.sub(
        r'    wire signed \[31:0\] is_bias_scalar =.*?'
        r'    wire signed \[63:0\] requant_in_vec_s64\[SIZE\];\n', '', region, flags=re.S)
    if removed == region:
        raise ValueError('Expected the scalar and requantization declarations')
    if 'is_bias_group_base <=' not in removed or 'is_bias_row_idx <=' not in removed:
        raise ValueError('Bias group state block is incomplete')
    return removed


def module_source(top):
    header = '''module bias_row_control #(
    parameter int unsigned SIZE = 16,
    parameter int unsigned REG_WIDTH = 32,
    parameter int unsigned BIAS_GROUP_BLOCKS_MAX = 32,
    localparam int unsigned IS_BIAS_ROWS = BIAS_GROUP_BLOCKS_MAX * SIZE,
    localparam int unsigned IS_BIAS_ROW_W = (IS_BIAS_ROWS <= 1) ? 1 : $clog2(IS_BIAS_ROWS),
    localparam int unsigned IS_BIAS_VALID_W =
        (IS_BIAS_ROWS <= 1) ? 1 : ($clog2(IS_BIAS_ROWS) + 1)
) (
    input logic clk, core_rst_n,
    input logic init_cfg_ia, is_mode, acc_data_valid,
    input logic bias_switch, send_ia_trigger, bias_sleep,
    input logic [REG_WIDTH-1:0] exec_m,
    input logic [IS_BIAS_VALID_W-1:0] is_bias_group_rows_target,
    output logic [IS_BIAS_ROW_W-1:0] o_row_idx, o_read_idx,
    output logic [REG_WIDTH-1:0] o_group_base, o_last_group_base,
    output logic [IS_BIAS_VALID_W-1:0] o_last_rows, o_rows_valid, o_rows_valid_pending
);
    logic [IS_BIAS_ROW_W-1:0] is_bias_row_idx;
    logic [IS_BIAS_ROW_W-1:0] is_bias_read_idx;
'''
    footer = '''
    assign o_row_idx = is_bias_row_idx;
    assign o_read_idx = is_bias_read_idx;
    assign o_group_base = is_bias_group_base;
    assign o_last_group_base = is_bias_last_group_base;
    assign o_last_rows = is_bias_last_rows;
    assign o_rows_valid = is_bias_rows_valid;
    assign o_rows_valid_pending = is_bias_rows_valid_pending;
endmodule
'''
    return header + control_region(top) + footer
