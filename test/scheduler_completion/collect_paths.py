#!/usr/bin/env python3
"""统计调度器完成通知、容量限制与帧计数的寄存器间组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, register_origins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    reports = {}
    for label in ('reference', 'current'):
        folder = args.native / label
        design = json.loads((folder / 'mapped.json').read_text())
        module = design['modules']['ps_scheduler_completion_measure']
        for name, origin in register_origins(folder / 'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        measured = json.loads((folder / 'metrics.json').read_text())
        result = {
            'resources': measured['resources'],
            'all_register_path': measured['paths']['longest_register_path_cells'],
        }
        for field, selector in (
            ('completion', lambda origin: origin == 'dut.done_ready'),
            ('pressure', lambda origin: origin.startswith('pressure_sampled')),
            ('opened', lambda origin: origin.startswith('dut.opened ')),
        ):
            paths = analyze(module, root_filter=lambda name, cell, port:
                selector(cell.get('attributes', {}).get('fpga_register_origin', '')),
                limit=1000, group_limit=1000)['paths']
            if not paths['graph_complete']:
                raise RuntimeError(f'组合路径分析未完成: {label}/{field}')
            result[field] = {
                'maximum': paths['longest_register_path_cells'],
                'groups': [[row['combinational_cells'], row['endpoint'].get('register_origin')]
                           for row in paths['distinct_register_path_groups']],
            }
        reports[label] = result
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports, indent=2) + '\n')
    print(json.dumps({label: {key: value['maximum'] for key, value in report.items()
                             if key in ('completion', 'pressure', 'opened')}
                      for label, report in reports.items()}, indent=2))


if __name__ == '__main__':
    main()
