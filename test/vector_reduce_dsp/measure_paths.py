#!/usr/bin/env python3
"""测量完整向量引擎中状态寄存器到归约寄存器的实际连接。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def measure(directory):
    mapped = directory / 'mapped.json'
    module = json.loads(mapped.read_text())['modules']['vector_engine']
    for name, origin in register_origins(directory / 'pre_lut.il').items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin

    def target(name, cell, port):
        return 'reduce_acc ' in cell.get('attributes', {}).get('fpga_register_origin', '')

    def state(name, cell, port):
        return re.fullmatch(r'state \[\d+\]',
                            cell.get('attributes', {}).get('fpga_register_origin', '')) is not None

    all_roots = connected_paths(module, limit=1, group_limit=0, sink_filter=target)
    state_roots = connected_paths(module, limit=1, group_limit=0, root_filter=state, sink_filter=target)
    assert all_roots['graph_complete'] and state_roots['graph_complete']
    return {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'pre_lut_sha256': hashlib.sha256((directory / 'pre_lut.il').read_bytes()).hexdigest(),
            'all_registers_to_reduce_acc': all_roots,
            'state_to_reduce_acc': state_roots}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = {'reference': measure(args.reference), 'current': measure(args.current)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({name: {group: values[group]['longest_register_path_cells']
                            for group in ('all_registers_to_reduce_acc', 'state_to_reduce_acc')}
                      for name, values in report.items()}))


if __name__ == '__main__':
    main()
