#!/usr/bin/env python3
"""从完整向量映射中提取舍入中间寄存器至结果寄存器的路径。"""
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
    parser.add_argument('--mapped', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    module = json.loads(args.mapped.read_text())['modules']['vector_engine']
    pre_lut = args.mapped.with_name('pre_lut.il')
    for name, origin in register_origins(pre_lut).items():
        if name in module['cells']:
            module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
    report = {'mapped_sha256': hashlib.sha256(args.mapped.read_bytes()).hexdigest(),
              'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(), 'paths': {}}
    for target in ('q_rounded', 'add_rounded'):
        for scope in ('all_registers', 'rounding_middle'):
            root_filter = None if scope == 'all_registers' else (
                lambda name, cell, port: 'u_rounding.' in cell.get('attributes', {}).get('fpga_register_origin', ''))
            paths = connected_paths(module, root_filter=root_filter,
                sink_filter=lambda name, cell, port: port == 'D' and
                cell.get('attributes', {}).get('fpga_register_origin', '').startswith(target + ' '))
            assert paths['graph_complete'] and paths['longest_register_path_cells'] > 0
            report['paths'][target + '_' + scope] = paths
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({name: paths['longest_register_path_cells'] for name, paths in report['paths'].items()}))


if __name__ == '__main__':
    main()
