#!/usr/bin/env python3
"""测量完整输出写回与 FIFO 银行状态更新的实际连接路径。"""
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
    report = {}
    for label, folder in [('reference', args.reference), ('current', args.current)]:
        mapped, pre_lut = folder / 'mapped.json', folder / 'pre_lut.il'
        module = json.loads(mapped.read_text())['modules']['fifo_bank_timing_top']
        for name, signal in register_origins(pre_lut).items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = signal
        prefix = 'u_fifo.g_full.u_full.'
        paths = {}
        for title, root in [('current_bank_to_bank_count', 'co_current_bank '),
                            ('bank_count_to_bank_count', 'bank_count['),
                            ('row_limit_to_bank_count', 'co_row_limit_q '),
                            ('row_to_bank_count', 'co_row ')]:
            paths[title] = connected_paths(module,
                root_filter=lambda name, cell, port: origin(cell).startswith(prefix + root),
                sink_filter=lambda name, cell, port: origin(cell).startswith(prefix + 'bank_count['))
        paths['all_fifo_endpoints'] = connected_paths(module,
            sink_filter=lambda name, cell, port: origin(cell).startswith('u_fifo.') or name.startswith('u_fifo.'))
        for detail in paths.values():
            assert detail['graph_complete']
            assert detail['longest_register_path_cells'] > 0
            if label == 'current':
                assert detail['longest_register_path_cells'] <= 15
        report[label] = {
            'mapped_sha256': hashlib.sha256(mapped.read_bytes()).hexdigest(),
            'pre_lut_sha256': hashlib.sha256(pre_lut.read_bytes()).hexdigest(),
            'paths': paths,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({label: {title: item['longest_register_path_cells']
                             for title, item in data['paths'].items()}
                      for label, data in report.items()}))


if __name__ == '__main__':
    main()
