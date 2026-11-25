#!/usr/bin/env python3
"""检查生产参数记录与逐项 DMA 时序比较的完整性。"""
from copy import deepcopy
import unittest

import run_production as runner


def result():
    rows = []
    for index in range(62):
        timing = {name: index + 1 for name in runner.TIMING_FIELDS}
        rows.append({"name": "case_" + str(index), "collection": "common",
                     "kind": "gemm", "cycles": timing["done"],
                     "output_sha256": "same_output", "passed": True,
                     "timing": timing,
                     "observed_production_parameters": dict(runner.EXPECTED_PARAMETERS)})
    return {"passed": True, "profile": dict(runner.EXPECTED_PARAMETERS),
            "input_manifest_sha256": "same_inputs", "cases": rows,
            "total_cycles": sum(row["cycles"] for row in rows),
            "source_commit": "test_commit"}


class ProductionComparison(unittest.TestCase):
    def test_equal_results(self):
        reference = result()
        self.assertTrue(runner.compare(reference, deepcopy(reference))["passed"])

    def test_each_dma_event_is_compared(self):
        reference = result()
        for name in runner.TIMING_FIELDS:
            with self.subTest(field=name):
                current = deepcopy(reference)
                current["cases"][0]["timing"][name] += 1
                comparison = runner.compare(reference, current)
                self.assertFalse(comparison["passed"])
                self.assertIn(name, comparison["cases"][0]["timing_field_differences"])

    def test_missing_event_and_parameter_are_rejected(self):
        reference = result()
        missing = deepcopy(reference)
        del missing["cases"][0]["timing"]["write_beats"]
        with self.assertRaises(ValueError):
            runner.compare(reference, missing)
        missing = deepcopy(reference)
        del missing["profile"]["matrix_requant_compute_lanes"]
        with self.assertRaises(ValueError):
            runner.compare(reference, missing)

    def test_simulated_parameter_log(self):
        log = ("COMMON_PRODUCTION_PARAMETERS matrix_requant_compute_lanes=2 "
               "vector_quantization_lanes=1 npu_address_width=32 "
               "matrix_dimension_count_width=29\n")
        self.assertEqual(runner.observed_parameters(log), runner.EXPECTED_PARAMETERS)
        for changed in (log.replace("lanes=2", "lanes=1"), "", log + log):
            with self.assertRaises(ValueError):
                runner.observed_parameters(changed)


if __name__ == "__main__":
    unittest.main()
