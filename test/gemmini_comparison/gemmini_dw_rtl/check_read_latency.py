#!/usr/bin/env python3
"""Verify exact configurable read latency and overlapping request waits."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sim', type=Path, required=True)
    parser.add_argument('--build-manifest', type=Path, required=True)
    parser.add_argument('--params-header', type=Path, required=True)
    parser.add_argument('--gemmini-tests', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    for latency in (1, 2, 3, 8, 17):
        measurements = {}
        for outstanding in (1, 4):
            directory = args.output / f'latency_{latency}_outstanding_{outstanding}'
            command = [sys.executable, str(HERE / 'check_axi64.py'),
                       '--sim', str(args.sim.resolve()),
                       '--build-manifest', str(args.build_manifest.resolve()),
                       '--params-header', str(args.params_header.resolve()),
                       '--gemmini-tests', str(args.gemmini_tests.resolve()),
                       '--output', str(directory.resolve()), '--read-interval', '1',
                       '--first-read-latency', str(latency),
                       '--inter-burst-gap-cycles', '1',
                       '--read-outstanding-limit', str(outstanding)]
            subprocess.run(command, check=True)
            result = json.loads((directory / 'results.json').read_text())
            measured = next(case for case in result['cases'] if case['name'] == 'outstanding_rows_4')
            measurements[outstanding] = measured
            rows.append(dict(first_read_latency=latency, outstanding_limit=outstanding,
                             read_span_cycles=measured['last_r_cycle'] - measured['first_r_cycle'],
                             first_r_minus_ar=measured['first_r_cycle'] - measured['first_ar_cycle'],
                             cycles=measured['cycles'], observed_outstanding=measured['max_read_outstanding_observed'],
                             matured_request_switch_gap_min=measured['matured_request_switch_gap_min'],
                             first_read_queue_delay_sum_cycles=measured['first_read_queue_delay_sum_cycles'],
                             first_read_backpressure_sum_cycles=measured['first_read_backpressure_sum_cycles'],
                             results=str((directory / 'results.json').resolve()), command=command))
        overlapped = measurements[4]['last_r_cycle'] - measurements[4]['first_r_cycle']
        serialized = measurements[1]['last_r_cycle'] - measurements[1]['first_r_cycle']
        if overlapped != 255 or serialized <= overlapped:
            raise ValueError(f'Latency {latency}: outstanding requests must hide the request waiting time')
    output = dict(passed=True, latencies=[1, 2, 3, 8, 17], outstanding_limits=[1, 4],
                  build_manifest_sha256=hashlib.sha256(args.build_manifest.read_bytes()).hexdigest(),
                  cases=rows)
    (args.output / 'results.json').write_text(json.dumps(output, indent=2) + '\n')
    print('READ_LATENCY_PASS configurations=10 protocol_cases=40', flush=True)


if __name__ == '__main__':
    main()
