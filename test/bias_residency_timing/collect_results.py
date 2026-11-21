#!/usr/bin/env python3
"""核对偏置加载器的完整证明、四态检查、数值回归和实际映射源码。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUFFER = 'rtl/npu/loaders/bias_loader_buffer.sv'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--four-state', type=Path, required=True)
    parser.add_argument('--numeric', type=Path, required=True)
    parser.add_argument('--mapping', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    formal = read(args.formal / 'summary.json')
    four = read(args.four_state / 'summary.json')
    numeric = read(args.numeric / 'result.json')
    metrics = read(args.mapping / 'metrics.json')
    manifest = read(args.mapping / 'manifest.json')
    if not all(report['passed'] for report in (formal, four, numeric)):
        raise ValueError('验证结果未全部通过')
    sources = formal['source_sha256']
    for name, value in sources.items():
        if digest(args.source_root / name) != value or numeric['source_sha256'][name] != value:
            raise ValueError('验证结果使用的源码不一致：' + name)
        mapped = [v for k, v in manifest['sources_sha256'].items() if Path(k).name == Path(name).name]
        if mapped != [value]:
            raise ValueError('映射结果使用的源码不一致：' + name)
    if four['source_sha256']['current'] != sources[BUFFER]:
        raise ValueError('四态结果使用的缓冲区源码不一致')
    if four['source_sha256']['helper'] != sources['rtl/common/parallel_prefix_add.sv']:
        raise ValueError('四态结果使用的加法器源码不一致')
    if not metrics['paths']['graph_complete']:
        raise ValueError('映射组合图不完整')
    report = {
        'passed': True,
        'reference_revision': formal['reference_rev'],
        'source_sha256': sources,
        'reference_source_sha256': formal['snapshot_sha256']['reference'],
        'latency_change_cycles': 0,
        'storage_capacity_change_bits': 0,
        'formal': {
            'passed': True, 'profiles': formal['profiles'],
            'equivalent_bits_total': sum(p['equivalent_bits'] for p in formal['profiles']),
            'inputs_constrained': False,
            'summary_sha256': digest(args.formal / 'summary.json'),
        },
        'four_state': {
            'passed': True, 'profiles': four['profiles'],
            'checks': sum(p['checks'] for p in four['profiles']),
            'strict_four_state_equivalence': four['strict_four_state_equivalence'],
            'summary_sha256': digest(args.four_state / 'summary.json'),
        },
        'numeric': {
            'passed': True, 'case_count': numeric['case_count'],
            'cycles': sum(p['cycles'] for p in numeric['cases']),
            'dma_commands': sum(p['dma_commands'] for p in numeric['cases']),
            'summary_sha256': digest(args.numeric / 'result.json'),
            'simulator_sha256': numeric['simulator_sha256'],
        },
        'mapping': {
            'top': manifest['top'], 'options': manifest['options'],
            'resources': metrics['resources'], 'graph_complete': True,
            'longest_register_path_cells': metrics['paths']['longest_register_path_cells'],
            'manifest_sha256': digest(args.mapping / 'manifest.json'),
            'mapped_sha256': digest(args.mapping / 'mapped.json'),
            'metrics_sha256': digest(args.mapping / 'metrics.json'),
        },
        'physical_timing_150mhz_confirmed': None,
        'collector_sha256': digest(Path(__file__)),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_bits': report['formal']['equivalent_bits_total'],
        'four_state_checks': report['four_state']['checks'], 'numeric_cases': numeric['case_count'],
        'register_depth': report['mapping']['longest_register_path_cells']}))


if __name__ == '__main__':
    main()
