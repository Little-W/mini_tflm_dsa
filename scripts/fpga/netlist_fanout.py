#!/usr/bin/env python3
"""统计映射网表的实际输入引脚扇出，并关联最长寄存器路径。"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import re

from netlist_metrics import FF_PATTERN, net_names


def analyze_fanout(module, paths=None, limit=20):
    names = net_names(module)
    cells = module['cells']
    loads = collections.Counter()
    clocks = collections.Counter()
    controls = collections.Counter()
    drivers = {}
    samples = collections.defaultdict(list)
    for name, cell in cells.items():
        kind = cell['type']
        for port, bits in cell['connections'].items():
            direction = cell['port_directions'][port]
            is_clock = (bool(FF_PATTERN.fullmatch(kind)) and port == 'C'
                        or port.startswith(('CLK', 'WCLK'))
                        or kind.startswith(('BUFG', 'BUFH')) and port in ('I', 'I0', 'I1'))
            is_control = (bool(FF_PATTERN.fullmatch(kind)) and port in ('CE', 'R', 'S', 'CLR', 'PRE')
                          or port.startswith(('CE', 'RST', 'WE', 'EN'))
                          or kind == 'DSP48E1' and port in ('OPMODE', 'ALUMODE', 'INMODE', 'CARRYINSEL'))
            for index, bit in enumerate(bits):
                if not isinstance(bit, int):
                    continue
                endpoint = {'cell': name, 'type': kind, 'port': port, 'index': index}
                if direction == 'output':
                    drivers[bit] = {**endpoint, 'source': cell.get('attributes', {}).get('src', ''),
                                    'register_origin': cell.get('attributes', {}).get('fpga_register_origin')}
                elif direction == 'input':
                    loads[bit] += 1
                    clocks[bit] += int(is_clock)
                    controls[bit] += int(is_control)
                    if len(samples[bit]) < 8:
                        samples[bit].append(endpoint)
    for port, item in module.get('ports', {}).items():
        if item['direction'] == 'input':
            for index, bit in enumerate(item['bits']):
                drivers.setdefault(bit, {'cell': None, 'type': 'primary_input', 'port': port, 'index': index})

    def describe(bit):
        return {'net': names.get(bit, str(bit)), 'input_pin_loads': loads[bit],
                'clock_pin_loads': clocks[bit], 'control_pin_loads': controls[bit],
                'nonclock_pin_loads': loads[bit] - clocks[bit],
                'driver': drivers.get(bit), 'load_samples': samples[bit]}

    nonclock = sorted((bit for bit in loads if loads[bit] > clocks[bit]),
                      key=lambda bit: (-(loads[bit] - clocks[bit]), names.get(bit, str(bit))))
    clock = sorted((bit for bit in loads if clocks[bit]), key=lambda bit: (-clocks[bit], bit))
    path_reports = []
    for path in (paths or {}).get('distinct_register_path_groups', []):
        path_nets = set()
        for step in path['path']:
            for field in ('input_port', 'output_port'):
                if ((field == 'input_port' and step.get('input_internal_registers'))
                        or (field == 'output_port' and step.get('output_internal_registers'))):
                    continue
                match = re.fullmatch(r'(.+)\[(\d+)\]', step[field])
                if not match:
                    raise ValueError('Unexpected path port: ' + step[field])
                port, index = match.group(1), int(match.group(2))
                bit = cells[step['cell']]['connections'][port][index]
                if isinstance(bit, int):
                    path_nets.add(bit)
        ranked = sorted(path_nets, key=lambda bit: (-loads[bit], names.get(bit, str(bit))))
        path_reports.append({'combinational_cells': path['combinational_cells'],
                             'startpoint': path['startpoint'], 'endpoint': path['endpoint'],
                             'maximum_pin_fanout': loads[ranked[0]] if ranked else 0,
                             'highest_fanout_nets': [describe(bit) for bit in ranked[:8]]})
    return {'maximum_nonclock_pin_fanout': loads[nonclock[0]] - clocks[nonclock[0]] if nonclock else 0,
            'nonclock_nets': [describe(bit) for bit in nonclock[:limit]],
            'clock_nets': [describe(bit) for bit in clock[:limit]],
            'register_path_groups': path_reports,
            'method': '按实际单元输入引脚计数，重复连接到不同引脚分别计数，常量不计入；时钟负载单独列出。扇出表示负载数量，实际延迟由器件和布线分析确定。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('netlist', type=Path)
    parser.add_argument('--top', default='soc_top')
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.netlist.read_text())['modules'][args.top]
    paths = json.loads(args.metrics.read_text())['paths'] if args.metrics else None
    args.out.write_text(json.dumps(analyze_fanout(module, paths), ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
