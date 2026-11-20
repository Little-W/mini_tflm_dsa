#!/usr/bin/env python3
"""比较完整向量引擎中的偏置写入和读取寄存器路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins, resources


def is_bias_register(cell):
    origin = cell.get('attributes', {}).get('fpga_register_origin', '')
    return 'bias_buf' in origin or '.u_bias_storage.mem' in origin


def measure(folder):
    netlist = folder / 'mapped.json'
    module = json.loads(netlist.read_text())['modules']['vector_engine']
    for name, origin in register_origins(folder / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    bias_bits = sum(is_bias_register(cell) for cell in module['cells'].values())
    assert bias_bits == 512, bias_bits
    paths = {}
    for port in ('D','CE'):
        def select(name, cell, selected_port):
            return is_bias_register(cell) and selected_port == port
        analysis = connected_paths(module,limit=1,group_limit=0,sink_filter=select)
        assert analysis['graph_complete']
        paths['write_' + port] = analysis['register_to_register_paths']
    analysis = connected_paths(module,limit=1,group_limit=0,
                               root_filter=lambda name,cell,port:is_bias_register(cell))
    assert analysis['graph_complete']
    paths['read'] = analysis['register_to_register_paths']
    overall = connected_paths(module,limit=1,group_limit=8)
    assert overall['graph_complete']
    return {'resources':resources(module['cells']),
            'mapped_sha256':hashlib.sha256(netlist.read_bytes()).hexdigest(),
            'bias_register_bits':bias_bits,'bias_paths':paths,
            'longest_register_path_cells':overall['longest_register_path_cells'],
            'distinct_register_path_groups':overall['distinct_register_path_groups']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    result = {'reference':measure(args.reference),'bank_write':measure(args.candidate)}
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2) + '\n')
    for name,item in result.items():
        print(name,{key:entries[0]['combinational_cells'] if entries else 0
                    for key,entries in item['bias_paths'].items()},
              'overall',item['longest_register_path_cells'])


if __name__ == '__main__':
    main()
