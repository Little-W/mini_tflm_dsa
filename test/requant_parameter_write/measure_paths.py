#!/usr/bin/env python3
"""统计 WS 参数写数据与写使能的实际寄存器间组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins, resources


def ws_register(name, cell):
    origin = cell.get('attributes', {}).get('fpga_register_origin', name)
    return ('g_ws_bank_write' in origin or any(signal in origin for signal in (
        'ch_multiplier_lane_r', 'ch_shift_lane_r', 'ch_product_multiplier_lane_r', 'ch_product_amount_lane_r')))


def measure(folder):
    netlist = folder / 'mapped.json'
    module = json.loads(netlist.read_text())['modules']['vec_requant']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    paths = {}
    for label, ports in [('data', {'D'}), ('enable', {'CE'})]:
        analysis = connected_paths(module, limit=1, group_limit=0,
            sink_filter=lambda name, cell, port: ws_register(name, cell) and port in ports)
        assert analysis['graph_complete']
        paths[label] = analysis['register_to_register_paths']
    return {'resources': resources(module['cells']),
            'mapped_sha256': hashlib.sha256(netlist.read_bytes()).hexdigest(),
            'ws_write_paths': paths}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--synthesis', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {name: measure(args.synthesis / name) for name in ('reference', 'bank_write')}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    for name, item in result.items():
        print(name, {port: entries[0]['combinational_cells'] if entries else None
                     for port, entries in item['ws_write_paths'].items()})


if __name__ == '__main__':
    main()
