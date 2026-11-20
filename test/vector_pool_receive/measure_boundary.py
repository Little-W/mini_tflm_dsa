#!/usr/bin/env python3
"""检查读响应输入至向量寄存器的实际组合连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--netlist', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--port', default='rd_valid', choices=('rd_valid', 'rd_done'))
    parser.add_argument('--bit', type=int, default=0)
    args = parser.parse_args()
    module = json.loads(args.netlist.read_text())['modules']['vector_engine']
    port_bits = module['ports'][args.port]['bits']
    if args.bit < 0 or args.bit >= len(port_bits):
        raise ValueError('The requested RTL index is outside the input port.')
    # rd_valid 的非压缩数组按 0 至 BUS_BYTES-1 声明；Slang 展平后，索引 0 位于最高位。
    mapped_index = len(port_bits) - 1 - args.bit if args.port == 'rd_valid' else args.bit
    rtl_name = f'{args.port}[{args.bit}]' if len(port_bits) > 1 else args.port
    mapped_name = f'{args.port}[{mapped_index}]' if len(port_bits) > 1 else args.port
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    boundary_name = 'response_input_boundary'
    module['cells'][boundary_name] = {
        'type': 'FDRE', 'parameters': {},
        'attributes': {'src': 'vector_engine.' + args.port,
                       'fpga_register_origin': args.port},
        'port_directions': {'Q': 'output', 'D': 'input', 'C': 'input', 'CE': 'input', 'R': 'input'},
        'connections': {'Q': [port_bits[mapped_index]], 'D': ['0'],
                        'C': ['0'], 'CE': ['0'], 'R': ['0']}}
    paths = connected_paths(module, root_filter=lambda name, cell, port: name == boundary_name)
    for key in ('register_to_register_paths', 'distinct_register_path_groups'):
        for path in paths[key]:
            path['startpoint'].update(cell='vector_engine', type='MODULE_INPUT',
                                      port=rtl_name, net=rtl_name, detail='module input',
                                      register_origin=None)
            if path['path'] and path['path'][0]['input_net'] == mapped_name:
                path['path'][0]['input_net'] = rtl_name
    result = {'scope': f'Module input {rtl_name} to actual synchronous data/control pins',
              'rtl_index': args.bit, 'flattened_port_bit_index': mapped_index,
              'netlist_sha256': hashlib.sha256(args.netlist.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'paths': paths}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'port': args.port, 'bit': args.bit,
                      'combinational_cells': paths['longest_register_path_cells'],
                      'graph_complete': paths['graph_complete']}))


if __name__ == '__main__':
    main()
