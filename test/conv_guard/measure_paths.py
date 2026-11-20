#!/usr/bin/env python3
"""统计读取保护器的寄存器和公开端口之间的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths


def measure(folder):
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['conv_axi_read_guard']
    registered = connected_paths(module, limit=1, group_limit=0)
    next_bit = max(bit for cell in module['cells'].values()
                   for bits in cell['connections'].values() for bit in bits
                   if isinstance(bit, int)) + 1
    for name, port in module['ports'].items():
        if name in ('clk', 'rst_n'):
            continue
        boundary = 'analysis_boundary_' + name
        if boundary in module['cells']:
            raise RuntimeError(f'Analysis boundary already exists: {boundary}')
        # 分析边界只表示外部时序起点和终点，不改变生产网表或组合深度。
        module['cells'][boundary] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' port boundary'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {
                'D': port['bits'] if port['direction'] == 'output' else [next_bit],
                'Q': port['bits'] if port['direction'] == 'input' else [next_bit],
            },
        }
        next_bit += 1
    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'register_to_register': registered, 'port_paths': {}}
    result['all_boundaries'] = connected_paths(module, limit=1, group_limit=0)
    for name in ('m_araddr', 's_arready'):
        result['port_paths'][name] = connected_paths(
            module, limit=1, group_limit=0,
            sink_filter=lambda cell_name, cell, port: cell_name == 'analysis_boundary_' + name)
    groups = [result['register_to_register'], result['all_boundaries'], *result['port_paths'].values()]
    if not all(group['graph_complete'] for group in groups):
        raise RuntimeError('Mapped connectivity graph is incomplete')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(path) for name, path in
              (('reference', args.reference), ('current', args.current))}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {'register_to_register': item['register_to_register']['longest_register_path_cells'],
                            'all_boundaries': item['all_boundaries']['longest_register_path_cells'],
                            **{port: value['longest_register_path_cells']
                               for port, value in item['port_paths'].items()}}
                      for name, item in result.items()}))


if __name__ == '__main__':
    main()
