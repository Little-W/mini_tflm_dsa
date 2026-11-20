#!/usr/bin/env python3
"""统计向量写回模块的真实组合级数和数据输出边界。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(folder):
    path = folder / 'mapped.json'
    module = json.loads(path.read_text())['modules']['vector_writeback']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    native = connected_paths(module, limit=4, group_limit=0)
    vectors = [bits for cell in module['cells'].values() for bits in cell['connections'].values()]
    vectors += [net['bits'] for net in module.get('netnames', {}).values()]
    next_bit = 1 + max(bit for bits in vectors for bit in bits if isinstance(bit, int))
    # 仅添加分析端点标识，原始综合网表及其中的组合连接保持不变。
    module['cells']['analysis_data_sink'] = {
        'type': 'FDRE', 'parameters': {},
        'attributes': {'fpga_register_origin': 'src_wdata output'},
        'port_directions': {'D': 'input', 'Q': 'output'},
        'connections': {'D': module['ports']['src_wdata']['bits'], 'Q': [next_bit]},
    }
    next_bit += 1
    output = connected_paths(module, limit=4, group_limit=0,
        sink_filter=lambda name, cell, port: name == 'analysis_data_sink')
    for name in ['result_words', 'request_address']:
        module['cells']['analysis_input_' + name] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' input'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': module['ports'][name]['bits']},
        }
        next_bit += 1
    interfaces = connected_paths(module, limit=4, group_limit=0)
    for item in [native, output, interfaces]:
        if not item['graph_complete']:
            raise RuntimeError('Incomplete combinational graph')
    return {'mapped_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'native_register_to_register': native,
            'register_to_data_output': output, 'including_interface_boundaries': interfaces}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(args.source / name) for name in ['reference', 'current']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {key: value['longest_register_path_cells']
                           for key, value in item.items() if isinstance(value, dict)}
                      for name, item in result.items()}))


if __name__ == '__main__':
    main()
