#!/usr/bin/env python3
"""汇总线性 DMA 后续地址的形式检查、事务回归及实际连接路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from netlist_metrics import connected_paths, register_origins


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--measurement', type=Path, required=True)
    parser.add_argument('--contexts', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    formal = read(args.formal / 'summary.json')
    inputs = read(args.measurement / 'inputs.json')
    synthesis = read(args.measurement / 'synthesis/summary.json')
    assert formal['passed'] and len(formal['runs']) == 11
    assert not formal['inputs_constrained']
    source_name = 'rtl/npu/dma/axi_linear_block_dma.sv'
    assert formal['original_reference_sha256'] == inputs['reference_source_sha256'][source_name]
    for name, value in inputs['source_sha256'].items():
        assert digest(ROOT / name) == value, name
        assert formal['source_sha256'][name] == value, name
    transactions = []
    totals = {'commands': 0, 'outputs': 0, 'cycles': 0}
    for folder in args.contexts:
        report = read(folder / 'summary.json')
        assert report['passed'] and report['sources_unchanged_during_build']
        for name, value in inputs['source_sha256'].items():
            assert report['source_sha256'][name] == value, name
        for run in report['runs']:
            assert run['passed']
            for name in totals:
                totals[name] += run['counters'][name]
        transactions.append(report)
    mapped = {}
    for label in ('reference', 'current'):
        folder = args.measurement / 'synthesis' / label
        manifest = read(folder / 'manifest.json')
        source = (args.measurement / 'inputs' / label / source_name).resolve()
        expected = (inputs['source_sha256'] if label == 'current' else
                    inputs['reference_source_sha256'])[source_name]
        assert digest(source) == expected
        assert manifest['sources_sha256'][str(source)] == expected
        for name, value in inputs['source_sha256'].items():
            if name != source_name:
                assert manifest['sources_sha256'][name] == value, name
        metrics = read(folder / 'metrics.json')
        assert metrics['paths']['graph_complete']
        if label == 'current':
            assert metrics['paths']['longest_register_path_cells'] <= 14
        module = read(folder / 'mapped.json')['modules']['axi_linear_block_dma']
        for name, origin in register_origins(folder / 'pre_lut.il').items():
            if name in module['cells']:
                module['cells'][name].setdefault('attributes', {})['fpga_register_origin'] = origin
        target = connected_paths(module, limit=4, group_limit=4,
            sink_filter=lambda name, cell, port:
                'rd_follow_addr' in cell.get('attributes', {}).get('fpga_register_origin', ''))
        mapped[label] = {
            'resources': metrics['resources'],
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'follow_address_paths': target,
            'graph_complete': True,
            'mapped_sha256': digest(folder / 'mapped.json'),
            'manifest_sha256': digest(folder / 'manifest.json'),
            'metrics_sha256': digest(folder / 'metrics.json'),
        }
    result = {
        'passed': True, **inputs,
        'behavior': {'public_cycles_changed': False, 'state_updates_changed': False},
        'formal': formal, 'transaction_profiles': transactions, 'transaction_totals': totals,
        'mapping_method': synthesis['method'], 'mapping': mapped,
        'physical_timing_150mhz_confirmed': None,
        'collector_sha256': digest(Path(__file__)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': 11, **totals}))


if __name__ == '__main__':
    main()
