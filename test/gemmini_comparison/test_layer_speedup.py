#!/usr/bin/env python3
"""验证性能阈值、输入完整性和不同计时起点的处理。"""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import check_layer_speedup as checks


class SpeedupChecks(unittest.TestCase):
    def test_exact_threshold(self):
        self.assertTrue(checks.threshold(5, 6)["passed"])
        self.assertFalse(checks.threshold(6, 7)["passed"])
        self.assertEqual(checks.threshold(6, 7)["cycles_above_target"], 1)

    def test_large_integer_threshold(self):
        scale = 1 << 53
        result = checks.threshold(5 * scale + 1, 6 * scale + 1)
        self.assertFalse(result["passed"])
        self.assertEqual(result["integer_check"]["npu_times_six"],
                         result["integer_check"]["gemmini_times_five"] + 1)

    def test_invalid_cycle_counts(self):
        for value in (0, -1, 5.0, True, "5", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                checks.threshold(value, 6)

    def test_complete_and_loop_start_are_both_checked(self):
        row = dict(name="dw", operation="depthwise", shape={}, npu=dict(cycles=5),
                   gemmini_native=dict(cycles=7, launch_to_complete_cycles=5))
        result = checks.measured_operator(row)
        self.assertTrue(result["complete_command"]["passed"])
        self.assertFalse(result["passed"])
        self.assertEqual(result["gemmini_interval"], "loop_launch_to_completion")

    def test_select_fastest_gemmini_candidate(self):
        row = dict(name="conv", operation="convolution", shape={}, npu=dict(cycles=10),
                   gemmini_native=dict(cycles=20, launch_to_complete_cycles=18),
                   gemmini_im2col=dict(cycles=11, launch_to_complete_cycles=-1))
        result = checks.measured_operator(row)
        self.assertEqual(result["gemmini_variant"], "gemmini_im2col")
        self.assertFalse(result["passed"])

    def test_invalid_loop_interval(self):
        row = dict(name="conv", operation="convolution", shape={}, npu=dict(cycles=10),
                   gemmini=dict(cycles=20, launch_to_complete_cycles=21))
        with self.assertRaises(ValueError):
            checks.measured_operator(row)

    def test_duplicate_and_empty_input_rejected(self):
        for rows in ([], [dict(name="a"), dict(name="a")]):
            with self.assertRaises(ValueError):
                checks.unique_rows(rows, lambda row: row["name"], "测试")
        with self.assertRaises(ValueError):
            checks.summarize([])

    def test_any_failed_item_fails_group(self):
        result = checks.summarize([checks.threshold(5, 6), checks.threshold(6, 7)])
        self.assertFalse(result["passed"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["passed_count"], 1)
        self.assertEqual(len(result["failed_items"]), 1)


class VectorResourceChecks(unittest.TestCase):
    def setUp(self):
        self.profile = dict(vector_pe_count=16, quantization_lanes=2, window_lanes=16)
        self.capacity = dict(elaborated_state=dict(module_instances=dict(vector_engine=1, vector_pe=16)),
            capability_parameters=dict(vector_engine=dict(PE_COUNT=16, QUANT_LANES=2, WINDOW_LANES=16)))

    def test_actual_vector_resources(self):
        self.assertEqual(checks.verify_vector_resources(self.profile, self.capacity),
                         dict(physical_pe_count=16, quantization_lanes=2, window_lanes=16))

    def test_instance_count_is_checked(self):
        self.capacity["elaborated_state"]["module_instances"]["vector_pe"] = 8
        with self.assertRaises(ValueError):
            checks.verify_vector_resources(self.profile, self.capacity)

    def test_every_parallel_parameter_is_checked(self):
        for key in ("PE_COUNT", "QUANT_LANES", "WINDOW_LANES"):
            capacity = copy.deepcopy(self.capacity)
            capacity["capability_parameters"]["vector_engine"][key] //= 2
            with self.subTest(parameter=key), self.assertRaises(ValueError):
                checks.verify_vector_resources(self.profile, capacity)

    def test_missing_parameter_is_rejected(self):
        del self.capacity["capability_parameters"]["vector_engine"]["QUANT_LANES"]
        with self.assertRaises(ValueError):
            checks.verify_vector_resources(self.profile, self.capacity)

    def test_shared_quantization_is_checked(self):
        self.profile.update(quantization_lanes=16, shared_quant_enable=1)
        self.capacity["capability_parameters"]["vector_engine"].update(QUANT_LANES=16, SHARED_QUANT_ENABLE=1)
        self.assertEqual(checks.verify_vector_resources(self.profile, self.capacity)["shared_quant_enable"], 1)
        self.capacity["capability_parameters"]["vector_engine"]["SHARED_QUANT_ENABLE"] = 0
        with self.assertRaises(ValueError):
            checks.verify_vector_resources(self.profile, self.capacity)


class CacheResourceChecks(unittest.TestCase):
    def setUp(self):
        self.profile = dict(im2col_cache_bytes=4096, cache_line_bytes=128, cache_ways=2, cache_sets=16)
        self.capacity = dict(capability_parameters=dict(npu_top=dict(
            CONV_LINE_BYTES=128, CONV_CACHE_WAYS=2, CONV_CACHE_SETS=16)))

    def test_same_physical_geometry(self):
        self.assertEqual(checks.verify_cache_resources(self.profile, self.capacity),
                         dict(cache_line_bytes=128, cache_ways=2, cache_sets=16))

    def test_different_line_width_is_rejected(self):
        self.profile["cache_line_bytes"] = 64
        with self.assertRaises(ValueError):
            checks.verify_cache_resources(self.profile, self.capacity)

    def test_inconsistent_capacity_is_rejected(self):
        self.profile["im2col_cache_bytes"] = 8192
        with self.assertRaises(ValueError):
            checks.verify_cache_resources(self.profile, self.capacity)


class ModelLayerChecks(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.model_path = self.root / "prepared/example/manifest.json"
        self.model_path.parent.mkdir(parents=True)
        self.node = dict(index=0, op="RESHAPE", input_shapes=[[1, 4]], output_shapes=[[4]], options={})
        self.manifest = dict(name="example", samples=[dict(sample_index=0), dict(sample_index=1)],
                             graph=dict(nodes=[self.node]))
        self.model_path.write_text(json.dumps(self.manifest))
        self.report = dict(passed=True, verification=dict(passed=True, complete_suite=True),
                           variants=dict(native={}, im2col={}), layer_samples=[])
        for sample in (0, 1):
            self.report["layer_samples"].append(dict(model="example", sample=sample, **self.node,
                output_exact=True, npu=dict(cycles=5), native=dict(cycles=6), im2col=dict(cycles=7)))

    def evaluate(self):
        path = self.root / "report.json"
        path.write_text(json.dumps(self.report))
        return checks.model_report(path, self.root / "prepared")

    def test_reshape_is_included(self):
        result = self.evaluate()
        self.assertTrue(result["passed"])
        self.assertEqual(result["items"][0]["operation"], "RESHAPE")
        self.assertEqual(result["sample_results"]["count"], 2)

    def test_missing_sample_rejected(self):
        self.report["layer_samples"].pop()
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_duplicate_sample_rejected(self):
        self.report["layer_samples"].append(copy.deepcopy(self.report["layer_samples"][0]))
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_changed_node_rejected(self):
        self.report["layer_samples"][0]["output_shapes"] = [[8]]
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_incorrect_output_rejected(self):
        self.report["layer_samples"][0]["output_exact"] = False
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_sample_failure_is_not_hidden_by_average(self):
        self.report["layer_samples"][0]["npu"]["cycles"] = 6
        self.report["layer_samples"][1]["npu"]["cycles"] = 4
        result = self.evaluate()
        self.assertFalse(result["items"][0]["passed"])
        self.assertTrue(result["items"][0]["aggregate_passed"])
        self.assertEqual(result["items"][0]["minimum_sample_speedup"], 1.0)
        self.assertEqual(result["minimum_sample_speedup"], 1.0)
        self.assertFalse(result["passed"])
        self.assertEqual(result["sample_results"]["passed_count"], 1)

    def test_empty_model_input_rejected(self):
        self.manifest["samples"] = []
        self.model_path.write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):
            self.evaluate()


if __name__ == "__main__":
    unittest.main()
