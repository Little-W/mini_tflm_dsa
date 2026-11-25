#!/usr/bin/env python3
"""分析完整偏置加载器的驻留寄存器输入与 bias_valid 输出组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def origin(cell):
    return str(cell.get('attributes', {}).get('fpga_register_origin', ''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped-case', type=Path, required=True)
    parser.add_argument('--low-index-width', type=int, default=5)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folder = args.mapped_case.resolve()
    module = json.loads((folder / 'mapped.json').read_text())['modules']['bias_loader']
    for name, source in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = source
    result = {'residency_inputs': connected_paths(module, limit=8, group_limit=8,
        sink_filter=lambda name, cell, port: 'resident_bank' in origin(cell))}

    # 图中的终点表示模块输出边界，仅用于路径分析，不写入综合网表和资源统计。
    next_bit = max(bit for net in module['netnames'].values()
                   for bit in net['bits'] if isinstance(bit, int)) + 1
    sink = 'bias_valid_analysis_endpoint'
    module['cells'][sink] = {
        'type': 'FDRE', 'parameters': {}, 'attributes': {},
        'port_directions': {'D': 'input', 'Q': 'output', 'C': 'input', 'R': 'input', 'CE': 'input'},
        'connections': {'D': module['ports']['bias_valid']['bits'], 'Q': [next_bit],
                        'C': module['ports']['clk']['bits'], 'R': ['0'], 'CE': ['1']},
    }

    def current_index(cell):
        return 'u_ctrl.current_block_idx' in origin(cell)

    def upper_index(cell):
        match = re.search(r'current_block_idx\s*\[(\d+)\]', origin(cell))
        return bool(match and int(match[1]) >= args.low_index_width)

    for name, predicate in [('all_registers_to_bias_valid', lambda cell: True),
                            ('current_index_to_bias_valid', current_index),
                            ('upper_index_to_bias_valid', upper_index)]:
        result[name] = connected_paths(module, limit=8, group_limit=8,
            root_filter=lambda name, cell, port: predicate(cell),
            sink_filter=lambda name, cell, port: name == sink)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {'maximum_cells': item['longest_register_path_cells'],
                             'reachable': bool(item['register_to_register_paths'])}
                      for name, item in result.items()}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
