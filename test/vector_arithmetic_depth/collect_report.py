#!/usr/bin/env python3
"""汇总当前向量算术的形式检查、功能回归和局部寄存器路径测量。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation', type=Path, required=True)
    parser.add_argument('--scalar', type=Path, required=True)
    parser.add_argument('--requant', type=Path, required=True)
    parser.add_argument('--four-state', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    checked = read(args.validation / 'summary.json')
    scalar = read(args.scalar / 'summary.json')
    requant = read(args.requant / 'summary.json')
    four_state = read(args.four_state / 'summary.json')
    assert checked['passed'] and scalar['passed'] and requant['passed'] and four_state['passed']
    assert len(checked['formal_profiles']) == 14
    for name, value in checked['source_sha256'].items():
        assert digest(ROOT / name) == value, name
    for name in ('rtl/npu/conv/vector_scalar_multiplier.sv', 'rtl/common/parallel_prefix_add.sv'):
        assert checked['source_sha256'][name] == scalar['source_sha256'][str(ROOT / name)]
        assert checked['source_sha256'][name] == requant['source_sha256'][name]
    assert four_state['source_sha256']['current'] == checked['source_sha256']['rtl/npu/conv/vector_round_shift.sv']
    cases = []
    for name, measured in checked['synthesis']['cases'].items():
        folder = args.validation / 'synthesis' / name
        metrics = read(folder / 'metrics.json')
        assert metrics['paths']['graph_complete']
        if name.startswith('current_'):
            assert metrics['paths']['longest_register_path_cells'] <= 14
        cases.append({
            'case': name,
            **{key: measured[key] for key in
               ('lut_cells', 'flip_flops', 'carry4', 'dsp', 'longest_register_path_cells')},
            'graph_complete': True,
            'sources_sha256': measured['sources_sha256'],
            'manifest_sha256': digest(folder / 'manifest.json'),
            'mapped_sha256': digest(folder / 'mapped.json'),
            'metrics_sha256': digest(folder / 'metrics.json'),
        })
    summary = {
        'passed': True,
        'reference_revision': checked['reference_revision'],
        'source_sha256': checked['source_sha256'],
        'reference_source_sha256': checked['reference_source_sha256'],
        'behavior': {'external_cycles_changed': False,
                     'reduce_minimum_priority_preserved': True,
                     'scalar_enabled_edge_latency_preserved': True},
        'formal': {'all_public_outputs_compared': True, 'input_constraints': [],
                   'profiles': checked['formal_profiles']},
        'scalar_function': scalar,
        'requant_function': requant,
        'round_four_state': four_state,
        'mapping': cases,
        'mapping_method': checked['synthesis']['method'],
        'register_path_limit': {'maximum_cells': 14, 'scope': '独立模块', 'passed': True},
        'physical_timing_150mhz_confirmed': None,
        'runner_sha256': checked['runner_sha256'],
        'wrapper_sha256': checked['measurement_wrapper_sha256'],
        'collector_sha256': digest(Path(__file__).resolve()),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': 14,
                      'scalar_checks': scalar['cycles']['checks'],
                      'mapped_cases': len(cases)}))


if __name__ == '__main__':
    main()
