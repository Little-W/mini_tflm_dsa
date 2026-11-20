#!/usr/bin/env python3
"""测量读取保护器页范围输入至公开握手输出的组合路径。"""
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
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['conv_axi_read_guard']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    native = connected_paths(module, limit=2, group_limit=0)
    bits = [bit for cell in module['cells'].values() for values in cell['connections'].values()
            for bit in values if isinstance(bit, int)]
    next_bit = max(bits) + 1
    for name, port in module['ports'].items():
        if name in ['clk', 'rst_n']:
            continue
        # 边界单元只供路径分析，生产综合网表保持不变。
        module['cells']['analysis_' + name] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' interface'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': port['bits'] if port['direction'] == 'output' else [next_bit],
                            'Q': port['bits'] if port['direction'] == 'input' else [next_bit]}}
        next_bit += 1
    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'native_register_paths': native, 'input_paths': {}}
    address_bits = module['ports']['s_araddr']['bits']
    for label, selected in [('all', address_bits), *[(str(bit), [address_bits[bit]]) for bit in range(3, 12)]]:
        module['cells']['analysis_s_araddr']['connections']['Q'] = selected
        result['input_paths'][label] = {}
        for target in ['m_arvalid', 's_arready']:
            paths = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda name, cell, port: name == 'analysis_s_araddr',
                sink_filter=lambda name, cell, port, expected=target: name == 'analysis_' + expected)
            assert paths['graph_complete']
            result['input_paths'][label][target] = paths
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(args.source / name) for name in ['reference', 'current']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {index: {target: paths['longest_register_path_cells']
        for target, paths in item.items()} for index, item in data['input_paths'].items()}
        for name, data in result.items()}))


if __name__ == '__main__':
    main()
