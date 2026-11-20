#!/usr/bin/env python3
"""根据实际真值表和输入连接计算 Xilinx LUT 各输出的组合依赖。"""
from __future__ import annotations

from functools import lru_cache
import re


LUT_PATTERN = re.compile(r'LUT(?:[1-6]|6_2)$')


@lru_cache(maxsize=16384)
def _sensitive_variables(table, bindings):
    """同一信号的全部引脚同时变化，常量引脚始终保持其连接值。"""
    count = max((value for value in bindings if value >= 0), default=-1) + 1
    values = []
    for assignment in range(1 << count):
        address = 0
        for pin, variable in enumerate(bindings):
            value = int(variable == -2) if variable < 0 else (assignment >> variable) & 1
            address |= value << pin
        values.append((table >> address) & 1)
    return frozenset(variable for variable in range(count)
        if any(values[assignment] != values[assignment ^ (1 << variable)]
               for assignment in range(1 << count) if not assignment & (1 << variable)))


def lut_output_dependencies(cell, output):
    """返回有影响的输入 (端口, 位序, 信号)；其他单元返回 None。

    INIT 缺失或含未知值时保留该输出全部可能的输入。未连接及未知输入
    作为独立自由变量参与分析，防止把尚未确定的逻辑简化为常量。
    """
    kind = cell['type']
    if not LUT_PATTERN.fullmatch(kind):
        return None
    if kind == 'LUT6_2':
        if output not in ('O5', 'O6'):
            raise ValueError('Unknown LUT6_2 output: ' + output)
        width = 5 if output == 'O5' else 6
    else:
        if output != 'O':
            raise ValueError('Unknown LUT output: ' + output)
        width = int(kind[-1])
    pins = []
    for index in range(width):
        port = f'I{index}'
        connected = cell['connections'].get(port, [])
        if len(connected) > 1:
            raise ValueError('LUT input must contain at most one bit: ' + port)
        pins.append((port, 0, connected[0] if connected else 'x'))
    value = cell.get('parameters', {}).get('INIT')
    if isinstance(value, str):
        value = value.strip()
        # O5 只读取低三十二位，其他输出读取所属原语的完整真值表。
        value = value[-(1 << width):]
        value = int(value, 2) if re.fullmatch(r'[01]+', value) else None
    if not isinstance(value, int) or value < 0:
        return tuple(pin for pin in pins if isinstance(pin[2], int))
    variables = {}
    bindings = []
    for port, _, bit in pins:
        if bit in ('0', '1'):
            bindings.append(-1 if bit == '0' else -2)
        else:
            key = ('net', bit) if isinstance(bit, int) else ('unknown', port)
            if key not in variables:
                variables[key] = len(variables)
            bindings.append(variables[key])
    sensitive = _sensitive_variables(value, tuple(bindings))
    return tuple(pin for pin, variable in zip(pins, bindings)
                 if isinstance(pin[2], int) and variable in sensitive)
