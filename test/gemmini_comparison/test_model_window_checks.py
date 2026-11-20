#!/usr/bin/env python3
"""检查实际窗口宽度、请求完成数和响应元素守恒的拒绝条件。"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / 'model_benchmark'
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('window_benchmark_run', BENCH / 'run.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
from verify_storage_models import verify_window_jobs


class ModelWindowChecks(unittest.TestCase):
    def example(self, lanes):
        row = dict(operation=2, requests=3, completions=3, peak_outstanding=3,
                   response_beats=4, requested_elements=4 * lanes,
                   response_elements=4 * lanes, return_span_cycles=5,
                   consecutive_responses=2, request_response_overlap=1)
        network = dict(dw_jobs=1, pool_jobs=0, dw_windows=3)
        return [row], network, dict(window_lanes=lanes, vector_window_outstanding=4)

    def accepted(self, rows, network, profile):
        self.assertTrue(all(bench.window_checks(rows, network, profile['window_lanes']).values()))
        verify_window_jobs(rows, network, profile)

    def rejected(self, rows, network, profile):
        self.assertFalse(all(bench.window_checks(rows, network, profile['window_lanes']).values()))
        with self.assertRaises(ValueError):
            verify_window_jobs(rows, network, profile)

    def test_actual_widths(self):
        for lanes in (4, 8, 16):
            with self.subTest(lanes=lanes):
                self.accepted(*self.example(lanes))

    def test_excess_elements(self):
        for lanes in (4, 8, 16):
            rows, network, profile = self.example(lanes)
            rows[0]['requested_elements'] += 1
            rows[0]['response_elements'] += 1
            with self.subTest(lanes=lanes):
                self.rejected(rows, network, profile)

    def test_missing_or_invalid_width(self):
        for value in (None, 0, -1, 16.0, True):
            rows, network, profile = self.example(16)
            if value is None:
                del profile['window_lanes']
            else:
                profile['window_lanes'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                bench.window_checks(rows, network, profile.get('window_lanes'))
            with self.subTest(value=value), self.assertRaises(ValueError):
                verify_window_jobs(rows, network, profile)

    def test_request_completion_conservation(self):
        rows, network, profile = self.example(16)
        rows[0]['completions'] -= 1
        self.rejected(rows, network, profile)

    def test_element_conservation(self):
        rows, network, profile = self.example(16)
        rows[0]['response_elements'] -= 1
        self.rejected(rows, network, profile)

    def test_zero_window_pool(self):
        rows, _, profile = self.example(16)
        rows[0] = {key: 0 for key in rows[0]}
        rows[0]['operation'] = 3
        self.accepted(rows, dict(dw_jobs=0, pool_jobs=1, dw_windows=0), profile)
        rows[0]['operation'] = 2
        self.rejected(rows, dict(dw_jobs=1, pool_jobs=0, dw_windows=0), profile)

    def test_outstanding_bound(self):
        rows, network, profile = self.example(16)
        rows[0]['peak_outstanding'] = 5
        self.rejected(rows, network, profile)

    def test_cycle_and_event_counts(self):
        for field, value in (('return_span_cycles', 3), ('consecutive_responses', 4),
                             ('request_response_overlap', 4), ('consecutive_responses', -1)):
            rows, network, profile = self.example(16)
            rows[0][field] = value
            with self.subTest(field=field, value=value):
                self.rejected(rows, network, profile)

    def test_record_and_network_totals(self):
        rows, network, profile = self.example(16)
        bad_network = copy.deepcopy(network)
        bad_network['dw_windows'] += 1
        self.rejected(rows, bad_network, profile)
        self.rejected([], network, profile)


if __name__ == '__main__':
    unittest.main()
