#!/usr/bin/env python3
"""检查实际DMA端口至读取突发长度寄存器的组合路径。"""
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
    full = connected_paths(module, limit=1, group_limit=0)
    bit_vectors = [bits for cell in module['cells'].values()
                   for bits in cell['connections'].values()]
    bit_vectors += [net['bits'] for net in module.get('netnames', {}).values()]
    bit_vectors += [port['bits'] for port in module['ports'].values()]
    next_bit = max(bit for bits in bit_vectors for bit in bits if isinstance(bit, int)) + 1
    input_names = ('rd_start', 'rd_base_addr', 'rd_burst_len_m1', 'm_axi_arready')
    for name in input_names:
        boundary = 'analysis_input_' + name
        if boundary in module['cells']:
            raise RuntimeError('Analysis boundary already exists: ' + boundary)
        # 这些边界只标出模块外的时序起点，不修改被测综合网表。
        module['cells'][boundary] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' input'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': module['ports'][name]['bits']},
        }
        next_bit += 1
    paths = {}
    for name in input_names:
        paths[name] = connected_paths(
            module, limit=1, group_limit=0,
            root_filter=lambda cell_name, cell, port, expected=name: cell_name == 'analysis_input_' + expected,
            sink_filter=lambda cell_name, cell, port:
                cell.get('attributes', {}).get('fpga_register_origin', '').startswith('rd_arlen_r ['))
        if not paths[name]['graph_complete'] or not paths[name]['register_to_register_paths']:
            raise RuntimeError('Incomplete path for ' + name)
    return {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'register_to_register': full, 'input_to_arlen': paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(folder) for name, folder in
              [('reference', args.reference), ('current', args.current)]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({label: {'register_to_register': data['register_to_register']['longest_register_path_cells'],
                             **{name: path['longest_register_path_cells']
                                for name, path in data['input_to_arlen'].items()}}
                      for label, data in result.items()}))


if __name__ == '__main__':
    main()
