#!/usr/bin/env python3
"""记录请求查询到 DMA 启动和缓存命中状态的实际映射路径。"""
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
        module = design['modules']['ia_lookup_capture_measure']
        for name, origin in register_origins(folder / 'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        measured = json.loads((folder / 'metrics.json').read_text())
        result = {'resources': measured['resources'],
                  'all_register_path': measured['paths']['longest_register_path_cells']}
        for field, selected_sink in (
            ('lookup_to_start', 'ext_dma_start'),
            ('lookup_to_hit', 'dut.cache_hit_done'),
            ('lookup_all_registers', None),
        ):
            sink_filter = (None if selected_sink is None else lambda name, cell, port:
                cell.get('attributes', {}).get('fpga_register_origin', '') == selected_sink)
            paths = analyze(module, root_filter=lambda name, cell, port:
                cell.get('attributes', {}).get('fpga_register_origin', '').startswith('dut.request_lookup_q '),
                sink_filter=sink_filter, limit=16, group_limit=128)['paths']
            if not paths['graph_complete']:
                raise RuntimeError('路径分析未完成: ' + label + '/' + field)
            result[field] = {'maximum': paths['longest_register_path_cells'],
                             'groups': paths['distinct_register_path_groups'],
                             'path': paths['register_to_register_paths'][:1]}
        reports[label] = result
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(reports, indent=2) + '\n')
    print(json.dumps({label: {key: report[key]['maximum'] for key in
                             ('lookup_to_start', 'lookup_to_hit', 'lookup_all_registers')}
                      for label, report in reports.items()}, indent=2))


if __name__ == '__main__':
    main()
