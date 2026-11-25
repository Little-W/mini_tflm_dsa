#!/usr/bin/env python3
"""按仿真实例和调用顺序比较偏置复用任务的数值检查、DMA 请求和周期。"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path


def indexed_cases(report):
    sequence = defaultdict(int)
    result = {}
    for row in report['cases']:
        instance = tuple(row[name] for name in ('is_mode', 'bus', 'capacity'))
        sequence[instance] += 1
        result[instance + (sequence[instance],)] = row
    return result


def compare(reference, current):
    old, new = indexed_cases(reference), indexed_cases(current)
    checks = {
        'both_passed': reference['passed'] and current['passed'],
        'same_fpga_mode': reference['fpga'] == current['fpga'],
        'same_tasks': set(old) == set(new) and len(old) == 392,
    }
    rows = []
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        configuration = ('is_mode', 'bus', 'capacity', 'channels', 'step', 'repeats')
        rows.append({
            'is_mode': key[0], 'bus': key[1], 'capacity': key[2], 'instance_case': key[3],
            'same_configuration': all(a[name] == b[name] for name in configuration),
            'same_dma_commands': a['dma_commands'] == b['dma_commands'],
            'reference_cycles': a['cycles'], 'current_cycles': b['cycles'],
            'no_cycle_regression': b['cycles'] <= a['cycles'],
        })
    for name in ('same_configuration', 'same_dma_commands', 'no_cycle_regression'):
        checks[name] = all(row[name] for row in rows)
    return {'passed': all(checks.values()), 'checks': checks, 'case_count': len(rows),
            'reference_total_cycles': sum(row['cycles'] for row in reference['cases']),
            'current_total_cycles': sum(row['cycles'] for row in current['cases']), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--current', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(json.loads(args.reference.read_text()), json.loads(args.current.read_text()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({name: result[name] for name in
                     ('passed', 'case_count', 'reference_total_cycles', 'current_total_cycles')}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
