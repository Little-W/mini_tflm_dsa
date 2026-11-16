#!/usr/bin/env python3
"""Exercise comparison checks using an existing verified AXI64 measurement set."""

import argparse
import copy
import json
from pathlib import Path

import compare_axi64_operators as comparison


def must_reject(action, expected):
    try:
        action()
    except ValueError as error:
        assert expected in str(error), str(error)
        return
    raise AssertionError('Invalid comparison input was accepted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    options = parser.parse_args()
    recorded = comparison.common.load(options.report)
    command = recorded['reproduction_command']
    fields = {command[i][2:].replace('-', '_'): command[i + 1] for i in range(2, len(command), 2)}
    fields = {key: int(value) if key in ('read_beat_cycles', 'first_read_latency', 'inter_burst_gap') else Path(value)
              for key, value in fields.items()}
    fields.setdefault('first_read_latency', 3)
    fields.setdefault('inter_burst_gap', 3)
    args = argparse.Namespace(**fields)
    actual = comparison.make_report(args)
    assert actual['comparison_verified'] and len(actual['gemm']) == 31 and len(actual['convolution']) == 5
    assert actual['gemm_target']['passed_count'] == sum(
        row['npu']['cycles'] < row['gemmini']['cycles'] for row in actual['gemm'])
    assert actual['all_requested_targets_passed'] == (
        actual['comparison_verified'] and actual['gemm_target']['passed'] and actual['dense_target']['strict_passed'])
    rejected_conditions = 0
    checker = comparison.Axi64Comparison(args)
    checker.verify_conditions()
    checker.documents['npu_gemm']['profile']['bus_bits'] = 32
    must_reject(checker.verify_conditions, 'Unexpected NPU parameter: bus_bits')
    rejected_conditions += 1
    checker.documents['npu_gemm']['profile']['bus_bits'] = 64
    checker.read_beat_cycles = 3 - args.read_beat_cycles
    must_reject(checker.verify_conditions, 'Gemmini memory service differs')
    rejected_conditions += 1
    checker.read_beat_cycles = args.read_beat_cycles
    checker.first_read_latency += 1
    must_reject(checker.verify_conditions, 'Gemmini memory service differs')
    rejected_conditions += 1
    checker.first_read_latency = args.first_read_latency
    checker.inter_burst_gap += 1
    must_reject(checker.verify_conditions, 'Gemmini memory service differs')
    rejected_conditions += 1
    checker.inter_burst_gap = args.inter_burst_gap
    if args.first_read_latency != 3 or args.inter_burst_gap != 3:
        memory = checker.documents['npu_gemm']['profile']['memory']
        memory['registered_synchronous_read'] = False
        must_reject(checker.verify_conditions, 'overlap independently timed synchronous reads')
        rejected_conditions += 1
        memory['registered_synchronous_read'] = True
        checker.npu_builds['gemm']['first_read_latency'] += 1
        must_reject(checker.verify_conditions, 'compiled first-response latency differs')
        rejected_conditions += 1
        checker.npu_builds['gemm']['first_read_latency'] = args.first_read_latency
    checker.documents['gemmini_native']['exporter_build']['vendor']['params_sha256'] = '0' * 64
    must_reject(checker.verify_conditions, 'exporter parameters differ')
    rejected_conditions += 1
    rows = copy.deepcopy(actual['gemm'])
    for row in rows:
        row['npu']['cycles'], row['gemmini']['cycles'] = 5, 6
        row['gemmini']['first_launch_cycle'] = 0
        row['gemmini']['launch_to_complete_cycles'] = 6
    exact = comparison.dense_target(rows, args.read_beat_cycles)
    assert exact['passed'] and exact['passed_count'] == 6 and exact['strict_passed']
    assert not exact['strict_failed_items']
    for item in exact['items']:
        check = item['loop_launch_integer_check']
        assert check['left_6_times_npu'] == check['right_5_times_gemmini']
        assert item['strict_cycles_above_target'] == 0
    for row in rows:
        row['gemmini']['first_launch_cycle'] = 1
        row['gemmini']['launch_to_complete_cycles'] = 5
    differing_start = comparison.dense_target(rows, args.read_beat_cycles)
    assert differing_start['passed'] and not differing_start['strict_passed']
    assert differing_start['strict_passed_count'] == 0
    assert len(differing_start['strict_failed_items']) == 6
    assert all(item['strict_cycles_above_target'] == 1 for item in differing_start['items'])
    for row in rows:
        row['npu']['cycles'], row['gemmini']['cycles'] = 5 * (1 << 52) + 1, 6 * (1 << 52) + 1
        row['gemmini']['first_launch_cycle'] = 0
        row['gemmini']['launch_to_complete_cycles'] = row['gemmini']['cycles']
    strict = comparison.dense_target(rows, args.read_beat_cycles)
    assert not strict['passed'] and strict['passed_count'] == 0 and not strict['strict_passed']
    for item in strict['items']:
        assert item['integer_check']['left_6_times_npu'] == item['integer_check']['right_5_times_gemmini'] + 1
    result = {
        'passed': True,
        'verified_gemm_cases': len(actual['gemm']),
        'verified_spatial_cases_per_policy': len(actual['convolution']),
        'rejected_condition_mismatches': rejected_conditions,
        'dense_integer_boundary_cases': 18,
        'measurement_report': comparison.common.artifact(options.report),
        'source_sha256': {Path(path).name: comparison.common.digest(Path(path)) for path in
                          (__file__, comparison.__file__, comparison.common.__file__)},
    }
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
