#!/usr/bin/env python3
"""检查逐字段比较的正差判定、零参考值及资源参数核对。"""
import unittest

from run import compare_numbers, verify_profile


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


if __name__ == "__main__":
    unittest.main()
