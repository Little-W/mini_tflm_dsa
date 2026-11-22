#!/usr/bin/env python3
"""汇总缓存实际参数验证、存储资源和组合路径结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import analyze, register_origins


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    folder = args.build.resolve()
    reports = {name: json.loads((folder / name / 'summary.json').read_text())
               for name in ('formal', 'four_state', 'cycle_production', 'synthesis')}
    if not all(report['passed'] for report in reports.values()):
        raise RuntimeError('缓存验证尚未全部通过')
    paths = {}
    for label in ('reference', 'current'):
        native = folder / 'synthesis/native' / label
        design = json.loads((native / 'mapped.json').read_text())
        module = design['modules']['conv_windowed_cache']
        for name, origin in register_origins(native / 'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        measured = analyze(module, root_filter=lambda name, cell, port:
            cell.get('attributes', {}).get('fpga_register_origin', '') == 'clearing',
            sink_filter=lambda name, cell, port:
            cell.get('attributes', {}).get('fpga_register_origin', '') == 'lookup_snapshot_valid',
            limit=16, group_limit=32)['paths']
        if not measured['graph_complete']:
            raise RuntimeError('缓存路径图未完成')
        warning_count = (native / '01_elaborate.log').read_text().count('asynchronous load value missing')
        paths[label] = {'clearing_to_lookup_snapshot_valid': measured['longest_register_path_cells'],
                        'path': measured['register_to_register_paths'][:1],
                        'asynchronous_load_warnings': warning_count}
    result = {
        'passed': True, 'source': 'rtl/npu/dma/cache/conv_read_cache.sv',
        'source_sha256': reports['four_state']['source_sha256'],
        'parameters': reports['synthesis']['parameters'],
        'formal': reports['formal']['profiles'],
        'four_state': reports['four_state'],
        'cycle_comparison': reports['cycle_production']['profiles'],
        'synthesis': {
            label: {'resources': report['resources'],
                    'longest_register_path_cells': report['paths']['longest_register_path_cells'],
                    **paths[label]}
            for label, report in reports['synthesis']['results'].items()},
        'reports': {name: {
            'path': str((folder / name / 'summary.json').relative_to(ROOT)),
            'sha256': hashlib.sha256((folder / name / 'summary.json').read_bytes()).hexdigest()}
            for name in reports},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({label: {'lut': report['resources']['lut_sites_nominal_before_packing'],
                             'maximum': report['longest_register_path_cells'],
                             'clearing': report['clearing_to_lookup_snapshot_valid']}
                      for label, report in result['synthesis'].items()}))


if __name__ == '__main__':
    main()
