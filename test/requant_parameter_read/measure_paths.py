#!/usr/bin/env python3
"""比较量化参数到乘法输入寄存器和移位量寄存器的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
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
    filters = {
        'multiplier_input': lambda name, cell, port:
            cell['type'] == 'DSP48E1' and '.u_product.' in name and port == 'B',
        'amount_input': lambda name, cell, port:
            '.amount_s0 ' in cell.get('attributes', {}).get('fpga_register_origin', '') and port == 'D',
    }
    paths = {}
    for name, select in filters.items():
        analysis = connected_paths(module, limit=1, group_limit=0, sink_filter=select)
        assert analysis['graph_complete']
        paths[name] = analysis['register_to_register_paths']
    return {'resources': resources(module['cells']),
            'mapped_sha256': hashlib.sha256(netlist.read_bytes()).hexdigest(),
            'parameter_paths': paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'reference': measure(args.reference), 'shared_read': measure(args.candidate)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for name, item in result.items():
        print(name, {port: entries[0]['combinational_cells'] if entries else None
                     for port, entries in item['parameter_paths'].items()})


if __name__ == '__main__':
    main()
