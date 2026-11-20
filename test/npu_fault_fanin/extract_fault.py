#!/usr/bin/env python3
"""从实际 NPU 顶层提取完整故障组合及仲裁器的中止连接。"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
TOP = Path('rtl/npu/top/npu_top.sv')
INPUTS = (
    ('ps_capacity_fault', 1), ('shared_ram_capacity_fault', 1),
    ('dma_bus_error', 1), ('frame_mode_q', 1), ('inner_done_valid', 1),
    ('inner_err_code', 2), ('run_conv', 1), ('run_vector', 1),
    ('conv_error', 1), ('abort_pending', 1),
)
INPUT_BITS = sum(width for _, width in INPUTS)


def region(source):
    start = '\n    wire ps_capacity_fault;'
    stop = '\n    wire controller_done_valid;'
    if source.count(start) != 1 or source.count(stop) != 1:
        raise ValueError('The complete task fault region must have unique boundaries')
    body = source.split(start, 1)[1].split(stop, 1)[0]
    if not re.search(r'\bassign\s+task_fault\s*=', body):
        raise ValueError('The task fault output is missing')
    if not re.search(r'\bwire\s+\[1:0\]\s+inner_err_code\s*;', source):
        raise ValueError('The error code input must retain its two-bit width')
    return start.lstrip('\n') + body


def abort_expression(source):
    marker = ') u_block_dma_arbiter ('
    if source.count(marker) != 1:
        raise ValueError('Expected the actual block DMA arbiter instance')
    body = source.split(marker, 1)[1].split('\n        );', 1)[0]
    matches = list(re.finditer(r'\.abort\s*\(', body))
    if len(matches) != 1:
        raise ValueError('Expected one abort connection on the block DMA arbiter')
    start = matches[0].end()
    depth = 1
    for end in range(start, len(body)):
        if body[end] == '(':
            depth += 1
        elif body[end] == ')':
            depth -= 1
            if depth == 0:
                return body[start:end].strip()
    raise ValueError('The abort expression is incomplete')


def module_source(source, name):
    body = region(source)
    lines = [f'module {name}(', f'    input logic [{INPUT_BITS-1}:0] i_flags,',
             '    output logic task_fault, arbiter_abort, selected_lut', ');']
    position = 0
    for signal, width in INPUTS:
        if signal != 'ps_capacity_fault':
            size = f'[{width-1}:0] ' if width != 1 else ''
            lines.append(f'    logic {size}{signal};')
        position += width
    lines.append(body)
    position = 0
    for signal, width in INPUTS:
        index = str(position) if width == 1 else f'{position+width-1}:{position}'
        lines.append(f'    assign {signal} = i_flags[{index}];')
        position += width
    selected = 'p_fault_use_lut' if 'p_fault_use_lut' in body else "1'b0"
    lines += [f'    assign arbiter_abort = {abort_expression(source)};',
              f'    assign selected_lut = {selected};', 'endmodule', '']
    return '\n'.join(lines)


def measurement_source(source):
    return module_source(source, 'fault_logic') + f'''
// 测量用寄存器仅定义输入和输出边界，不属于生产 RTL。
module fault_measure(input logic clk,
    input logic [{INPUT_BITS-1}:0] i_flags, output logic [1:0] o_flags);
    logic [{INPUT_BITS-1}:0] captured_flags;
    logic [1:0] fault_outputs;
    always_ff @(posedge clk) begin
        captured_flags <= i_flags;
        o_flags <= fault_outputs;
    end
    fault_logic u_fault_logic(
        .i_flags(captured_flags),
        .task_fault(fault_outputs[0]), .arbiter_abort(fault_outputs[1]),
        .selected_lut()
    );
endmodule
'''
