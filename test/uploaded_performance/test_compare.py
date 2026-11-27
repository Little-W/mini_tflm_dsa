#!/usr/bin/env python3
"""检查逐字段比较的正差判定、零参考值及资源参数核对。"""
import unittest

from run import compare_numbers, summarize_cycles, verify_profile


class PerformanceComparisonTest(unittest.TestCase):
    def test_single_cycle_increase(self):
        rows = compare_numbers({"cycles": 1_000_000}, {"cycles": 1_000_001})
        self.assertEqual(rows[0]["status"], "increased")
        self.assertEqual(rows[0]["delta"], 1)
        self.assertAlmostEqual(rows[0]["change_percent"], 0.0001)

    def test_zero_reference_wait(self):
        rows = compare_numbers({"read_wait": 0}, {"read_wait": 1})
        self.assertEqual(rows[0]["status"], "increased")
        self.assertEqual(rows[0]["delta"], 1)
        self.assertIsNone(rows[0]["change_percent"])

    def test_dma_and_event_fields(self):
        previous = {"measurement": {"ar_bytes": 64, "ar_requests": 1}, "timing": {"first_r": 8}}
        current = {"measurement": {"ar_bytes": 72, "ar_requests": 2}, "timing": {"first_r": 7}}
        rows = {row["field"]: row for row in compare_numbers(previous, current)}
        self.assertEqual(rows["measurement.ar_bytes"]["delta"], 8)
        self.assertEqual(rows["measurement.ar_requests"]["delta"], 1)
        self.assertEqual(rows["timing.first_r"]["status"], "decreased")

    def test_missing_field_is_explicit(self):
        rows = {row["field"]: row for row in compare_numbers({"a": 1}, {"b": 2})}
        self.assertEqual(rows["a"]["status"], "removed")
        self.assertEqual(rows["b"]["status"], "added")
        self.assertIsNone(rows["a"]["delta"])
        self.assertIsNone(rows["b"]["delta"])

    def test_same_values(self):
        value = {"timing": {"done": 210}, "waits": [{"read": 8, "write": 4}]}
        self.assertTrue(all(row["status"] == "equal" for row in compare_numbers(value, value)))

    def test_capacity_change_is_rejected(self):
        reference = {"size": 16, "shared_bank_bytes": 4096, "conv_register_descriptor": 0}
        current = {"size": 16, "shared_bank_bytes": 8192, "conv_register_descriptor": 1,
                   "rtl_simulation_defines": ["SYNTHESIS", "XILINX_FPGA"]}
        with self.assertRaises(ValueError):
            verify_profile(current, reference, {"conv_register_descriptor": 1})

    def test_actual_pipeline_parameter(self):
        reference = {"size": 16, "shared_bank_bytes": 4096, "conv_register_descriptor": 0}
        current = {"size": 16, "shared_bank_bytes": 4096, "conv_register_descriptor": 1,
                   "rtl_simulation_defines": ["SYNTHESIS", "XILINX_FPGA"]}
        verify_profile(current, reference, {"conv_register_descriptor": 1})
        with self.assertRaises(ValueError):
            verify_profile(current, reference, {"conv_register_descriptor": 0})

    def test_production_macros(self):
        with self.assertRaises(ValueError):
            verify_profile({"size": 16, "rtl_simulation_defines": ["SYNTHESIS"]}, {"size": 16}, {})

    def test_cycle_totals_and_largest_increases(self):
        cases = [{"collection": "operators", "kind": "gemm", "name": name,
                  "checkpoint_cycles": before, "measured_cycles": after}
                 for name, before, after in (("large", 1000, 1010), ("small", 10, 11),
                                             ("equal", 30, 30), ("faster", 100, 50))]
        result = summarize_cycles(cases)
        self.assertEqual(result["reference_cycles"], 1140)
        self.assertEqual(result["current_cycles"], 1101)
        self.assertEqual(result["cycle_delta"], -39)
        self.assertAlmostEqual(result["cycle_change_percent"], -3900 / 1140)
        self.assertEqual(result["increased_case_count"], 2)
        self.assertEqual(result["decreased_case_count"], 1)
        self.assertEqual(result["equal_case_count"], 1)
        self.assertEqual(result["maximum_cycle_increase"]["name"], "large")
        self.assertEqual(result["maximum_relative_cycle_increase"]["name"], "small")
        self.assertEqual(result["maximum_relative_cycle_increase"]["cycle_change_percent"], 10.0)

    def test_no_increased_cycle_count(self):
        cases = [{"collection": "operators", "kind": "gemm", "name": "same",
                  "checkpoint_cycles": 7, "measured_cycles": 7}]
        result = summarize_cycles(cases)
        self.assertEqual(result["cycle_change_percent"], 0.0)
        self.assertEqual(result["increased_case_count"], 0)
        self.assertIsNone(result["maximum_cycle_increase"])
        self.assertIsNone(result["maximum_relative_cycle_increase"])

    def test_zero_reference_cycles_are_rejected(self):
        with self.assertRaises(ValueError):
            summarize_cycles([{"collection": "operators", "kind": "gemm", "name": "invalid",
                               "checkpoint_cycles": 0, "measured_cycles": 1}])


if __name__ == "__main__":
    unittest.main()
