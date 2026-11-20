#!/usr/bin/env python3
"""从实际映射网表统计归约偏移寄存器到各接收寄存器的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, connected_paths, register_origins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--pre-lut', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['conv_im2col_frontend']
    for name, origin in register_origins(args.pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    result = {'netlist_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(args.pre_lut.read_bytes()).hexdigest(),
              'complete_module': analyze(module), 'register_groups': {}}
    for signal in ('q0', 'next_group_q'):
        pattern = re.compile(re.escape(signal) + r' \[')
        selected = lambda name, cell, port: bool(pattern.match(cell.get('attributes', {}).get('fpga_register_origin') or ''))
        paths = connected_paths(module, limit=100000, group_limit=100000, root_filter=selected)
        state = [path for path in paths['register_to_register_paths']
                 if (path['endpoint'].get('register_origin') or '').startswith('state ')]
        result['register_groups'][signal] = {
            'longest_path_cells': paths['longest_register_path_cells'],
            'longest_state_path_cells': max((path['combinational_cells'] for path in state), default=0),
            'longest_paths': paths['register_to_register_paths'][:3], 'state_paths': state[:3]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print({name: {key: data[key] for key in ('longest_path_cells', 'longest_state_path_cells')}
           for name, data in result['register_groups'].items()})


if __name__ == '__main__':
    main()
