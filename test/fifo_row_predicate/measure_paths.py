#!/usr/bin/env python3
"""测量真实写回与 FIFO 联合网表中的行号和银行计数路径。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def origin(cell):
    return cell.get('attributes', {}).get('fpga_register_origin', '')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    summary = {}
    for label, folder in (('reference', args.reference), ('current', args.current)):
        mapped, pre_lut = folder / 'mapped.json', folder / 'pre_lut.il'
        module = json.loads(mapped.read_text())['modules']['oa_fifo_timing_top']
        for name, signal in register_origins(pre_lut).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = signal
        scopes = {
            'bank_count_to_bank_count': 'u_fifo.bank_count[',
            'co_row_to_bank_count': 'u_fifo.co_row ',
            'row_limit_to_bank_count': 'u_fifo.co_row_limit_q ',
        }
        reports = {}
        for scope, prefix in scopes.items():
            reports[scope] = connected_paths(module,
                root_filter=lambda name, cell, port: origin(cell).startswith(prefix),
                sink_filter=lambda name, cell, port: origin(cell).startswith('u_fifo.bank_count['))
        reports['all_fifo_endpoints'] = connected_paths(module,
            sink_filter=lambda name, cell, port: origin(cell).startswith('u_fifo.') or name.startswith('u_fifo.'))
        for scope, paths in reports.items():
            assert paths['graph_complete']
            if scope != 'row_limit_to_bank_count' or label == 'current':
                assert paths['longest_register_path_cells'] > 0
            if label == 'current':
                assert paths['longest_register_path_cells'] <= 15
        summary[label] = {'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
                          'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
                          'paths': reports}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({label: {scope: paths['longest_register_path_cells']
                             for scope, paths in row['paths'].items()} for label, row in summary.items()}))


if __name__ == '__main__':
    main()
