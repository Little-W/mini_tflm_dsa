#!/usr/bin/env python3
"""比较量化尾部通道数、行数到消费寄存器的完整组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins, resources


def measure(folder):
    netlist = folder / 'mapped.json'
    module = json.loads(netlist.read_text())['modules']['vec_requant']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    paths = {}
    for register in ('lane_en_s0', 'lane_need_q', 'row_in_tile_cnt'):
        def select(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin', '')
            return re.search(r'\.' + register + r'(?: \[|$)', origin) is not None and port == 'D'
        analysis = connected_paths(module, limit=1, group_limit=0, sink_filter=select)
        assert analysis['graph_complete']
        paths[register] = analysis['register_to_register_paths']
    for dimension in ('m_r', 'k_r'):
        def select(name, cell, port):
            origin = cell.get('attributes', {}).get('fpga_register_origin', '')
            return ('.' + dimension + ' ') in origin
        analysis = connected_paths(module, limit=1, group_limit=0, root_filter=select)
        assert analysis['graph_complete']
        paths['from_' + dimension] = analysis['register_to_register_paths']
    overall = connected_paths(module, limit=1, group_limit=8)
    assert overall['graph_complete']
    return {'resources': resources(module['cells']),
            'mapped_sha256': hashlib.sha256(netlist.read_bytes()).hexdigest(),
            'geometry_paths': paths,
            'longest_register_path_cells': overall['longest_register_path_cells'],
            'distinct_register_path_groups': overall['distinct_register_path_groups']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'reference': measure(args.reference), 'tail_count': measure(args.candidate)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for name, item in result.items():
        print(name, {register: entries[0]['combinational_cells'] if entries else None
                     for register, entries in item['geometry_paths'].items()},
              'overall', item['longest_register_path_cells'])


if __name__ == '__main__':
    main()
