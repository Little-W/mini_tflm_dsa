#!/usr/bin/env python3
"""测量读取合并计算到突发长度及后续地址的实际组合路径。"""
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
    module = json.loads(mapped.read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    native = connected_paths(module, limit=3, group_limit=0)
    vectors = [bits for cell in module['cells'].values() for bits in cell['connections'].values()]
    vectors += [net['bits'] for net in module.get('netnames', {}).values()]
    next_bit = 1 + max(bit for bits in vectors for bit in bits if isinstance(bit, int))
    input_names = ['rd_start', 'rd_base_addr', 'rd_burst_len_m1',
                   'rd_rows_to_read', 'rd_row_stride', 'm_axi_arready']
    for name in input_names:
        # 这些分析起点只标记接口边界，实际综合网表保持不变。
        module['cells']['analysis_input_' + name] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' input'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': module['ports'][name]['bits']},
        }
        next_bit += 1
    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'native_register_to_register': native, 'input_paths': {}}
    for target in ['rd_follow_addr', 'rd_follow_beats', 'rd_arlen_r']:
        result['input_paths'][target] = {}
        for name in input_names:
            path = connected_paths(module, limit=1, group_limit=0,
                root_filter=lambda cell_name, cell, port, expected=name:
                    cell_name == 'analysis_input_' + expected,
                sink_filter=lambda cell_name, cell, port, expected=target:
                    cell.get('attributes', {}).get('fpga_register_origin', '').startswith(expected + ' ['))
            if not path['graph_complete']:
                raise RuntimeError('Incomplete path graph')
            result['input_paths'][target][name] = path
    for name, cell in list(module['cells'].items()):
        if cell['type'] == 'DSP48E1':
            # 仅把DSP输出端口设为路径分析起点，保持实际电路及其寄存器配置不变。
            module['cells']['analysis_dsp_output_' + name] = {
                'type': 'FDRE', 'parameters': {},
                'attributes': {'fpga_register_origin': name + ' P output'},
                'port_directions': {'Q': 'output'}, 'connections': {'Q': cell['connections']['P']}}
    result['dsp_output_port_paths'] = {}
    for target in ('rd_follow_addr', 'rd_arlen_r'):
        result['dsp_output_port_paths'][target] = connected_paths(module, limit=3, group_limit=3,
            root_filter=lambda n, c, p: n.startswith('analysis_dsp_output_'),
            sink_filter=lambda n, c, p, expected=target:
                c.get('attributes', {}).get('fpga_register_origin', '').startswith(expected + ' ['))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'reference': measure(args.reference), 'current': measure(args.current)}
    print({name: {target: item['longest_register_path_cells'] for target, item in data['dsp_output_port_paths'].items()} for name, data in result.items()})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: {target: {source: path['longest_register_path_cells']
                                   for source, path in paths.items()}
                            for target, paths in data['input_paths'].items()}
                      for name, data in result.items()}))


if __name__ == '__main__':
    main()
