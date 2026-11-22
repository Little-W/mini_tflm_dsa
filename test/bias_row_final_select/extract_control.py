#!/usr/bin/env python3
"""从实际输出模块提取偏置组状态、读取索引和行索引逻辑。"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_output_pipeline.sv')
LEGACY_TOP = Path('rtl/npu/top/npu_top.sv')
DEFAULT_REFERENCE = 'ca34494'


def read_control_source(root=ROOT, reference=None):
    """返回实际含偏置控制的文件及内容，兼容模块拆分前后的版本。"""
    root = Path(root)
    if reference is None:
        path = TOP if (root / TOP).is_file() else LEGACY_TOP
        return path, (root / path).read_text()
    for path in (TOP, LEGACY_TOP):
        result = subprocess.run(['git', 'show', f'{reference}:{path}'], cwd=root,
                                capture_output=True, text=True)
        if result.returncode == 0:
            return path, result.stdout
    raise ValueError(f'找不到版本 {reference} 中的偏置控制源码')


def control_region(source):
    output = re.search(r'\bmodule\s+npu_output_pipeline\b.*?\bendmodule\b', source, re.S)
    if output:
        text = output.group(0)
        parameters = re.findall(r'^\s*localparam\s+int\s+unsigned\s+p_bias_\w+\s*=.*?;',
                                text, re.M | re.S)
        declarations = []
        for declaration in re.findall(r'^\s*logic\s+[^;]*\bis_bias_\w+\s*;', text, re.M):
            if not re.search(r'\b(?:is_bias_row_idx|is_bias_scalar)\s*;', declaration):
                declarations.append(declaration)
        start = re.search(r'^\s*assign\s+is_bias_group_rows_target_ext\b', text, re.M).start()
        end = re.search(r'^\s*genvar\s+rq_i\s*;', text[start:], re.M).start() + start
        statements = re.sub(r'^\s*assign\s+is_bias_scalar\s*=.*?;', '',
                            text[start:end], flags=re.M | re.S)
        region = '\n'.join(parameters + declarations) + '\n' + statements
        names = {
            'p_reg_width': 'REG_WIDTH', 'p_is_bias_row_w': 'IS_BIAS_ROW_W',
            'p_is_bias_valid_w': 'IS_BIAS_VALID_W', 'rst_n': 'core_rst_n',
            'i_is_bias_group_rows_target': 'is_bias_group_rows_target',
            'o_is_bias_read_idx': 'is_bias_read_idx',
            **{f'i_{name}': name for name in ('exec_m', 'init_cfg_ia', 'is_mode',
                'acc_data_valid', 'bias_switch', 'send_ia_trigger', 'bias_sleep')},
        }
        region = re.sub(r'\b(?:' + '|'.join(names) + r')\b',
                        lambda match: names[match.group(0)], region)
    else:
        start = re.search(r'^\s*logic\s+\[REG_WIDTH-1:0\]\s+is_bias_group_base\s*;',
                          source, re.M).start()
        end = re.search(r'^\s*genvar\s+rq_i\s*;', source[start:], re.M).start() + start
        region = re.sub(
            r'^\s*(?:wire|logic)\s+signed\s+\[(?:31|63):0\]\s+'
            r'(?:is_bias_scalar|requant_in_vec(?:_s64)?)\b.*?;', '',
            source[start:end], flags=re.M | re.S)
    if 'is_bias_group_base <=' not in region or 'is_bias_row_idx <=' not in region:
        raise ValueError('偏置组状态过程提取不完整')
    return region


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
    input logic [31:0] exec_m,
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
