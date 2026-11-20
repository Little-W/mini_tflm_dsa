#!/usr/bin/env python3
"""统计映射网表中到预取选择与描述寄存器的组合路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins

TARGETS = ('pf_pick', 'pf_addr', 'pf_index', 'pf_epoch', 'pf_retire', 'pf_index_valid')


def measure(directory):
    mapped = directory / 'mapped.json'
    pre_lut = directory / 'pre_lut.il'
    module = json.loads(mapped.read_text())['modules']['conv_windowed_cache']
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    paths = connected_paths(module, limit=100000, group_limit=100000)
    if not paths['graph_complete'] or paths['combinational_cycle_nodes']:
        raise RuntimeError('The complete acyclic combinational graph is required')
    targets = {}
    for target in TARGETS:
        matches = [path for path in paths['register_to_register_paths']
                   if path['endpoint']['category'] == 'data' and
                   re.match(r'^' + target + r'(?: |$)',
                            path['endpoint'].get('register_origin') or '')]
        if not matches:
            raise RuntimeError('No data path found for ' + target)
        targets[target] = matches[0]
    return {'source': str(directory),
            'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
            'graph_complete': paths['graph_complete'],
            'combinational_cycle_nodes': paths['combinational_cycle_nodes'],
            'paths': targets}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'reference': measure(args.reference.resolve()),
              'current': measure(args.current.resolve())}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({side: {target: path['combinational_cells']
                            for target, path in data['paths'].items()}
                      for side, data in result.items()}))


if __name__ == '__main__':
    main()
