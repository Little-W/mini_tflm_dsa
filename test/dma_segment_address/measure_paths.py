#!/usr/bin/env python3
"""比较 DMA 命令参数和行地址至后续突发地址寄存器的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

INPUTS = ('rd_burst_len_m1', 'rd_base_addr', 'rd_rows_to_read', 'rd_row_stride')
REGISTERS = ('rd_follow_addr', 'rd_cmd_row_addr')


def measure(folder):
    mapped = folder / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['axi_linear_block_dma']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
              'register_to_register': connected_paths(module, limit=1, group_limit=0),
              'follow_address_paths': {}}
    next_bit = max(bit for cell in module['cells'].values()
                   for bits in cell['connections'].values() for bit in bits
                   if isinstance(bit, int)) + 1
    for name in INPUTS:
        boundary = 'analysis_input_' + name
        if boundary in module['cells']:
            raise RuntimeError(f'Analysis boundary already exists: {boundary}')
        # 边界仅用于描述组合输入的起点，综合网表不增加寄存器。
        module['cells'][boundary] = {
            'type': 'FDRE', 'parameters': {},
            'attributes': {'fpga_register_origin': name + ' input'},
            'port_directions': {'D': 'input', 'Q': 'output'},
            'connections': {'D': [next_bit], 'Q': module['ports'][name]['bits']},
        }
        next_bit += 1
    for start in INPUTS + REGISTERS:
        def source_selected(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin') or ''
            return origin.rsplit(' [', 1)[0] in (start, start + ' input')

        def target_selected(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin') or ''
            return origin.startswith('rd_follow_addr [')

        group = connected_paths(module, limit=1, group_limit=0,
                                root_filter=source_selected, sink_filter=target_selected)
        if not group['graph_complete'] or not group['register_to_register_paths']:
            raise RuntimeError(f'Incomplete path from {start} to rd_follow_addr')
        result['follow_address_paths'][start] = group['register_to_register_paths'][0]
    if not result['register_to_register']['graph_complete']:
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
    print(json.dumps({name: {'register_to_register': data['register_to_register']['longest_register_path_cells'],
                            **{start: path['combinational_cells']
                               for start, path in data['follow_address_paths'].items()}}
                      for name, data in result.items()}))


if __name__ == '__main__':
    main()
