"""验证容量报告只适用于相同的实现目标与计算并行度。"""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration, model


class ElaborationTargetTests(unittest.TestCase):
    def setUp(self):
        self.values = {**config.DEFAULTS, "CAPACITY_BUDGET_SCOPE": "logical-state"}
        self.sources = {"rtl/npu/top/npu_top.sv": "source-sha256"}
        self.report = {
            "passed": True, "elaboration_target": "generic",
            "hardware_configuration": elaboration.hardware_config(self.values),
            "source_sha256": self.sources, "cache_identity": "measurement-sha256",
            "verilator": "test", "elaborated_state": {"total_bits": 80000 * 8},
        }

    def test_implementation_targets_have_separate_identities(self):
        self.assertNotEqual(elaboration.identity(self.values, self.sources, target="asic"),
                            elaboration.identity(self.values, self.sources, target="generic"))

    def test_generic_measurement_cannot_validate_asic_configuration(self):
        with patch.object(elaboration, "sources_sha256", return_value=self.sources):
            self.assertTrue(elaboration.current_report(self.values, self.report, target="generic"))
            self.assertFalse(elaboration.current_report(self.values, self.report, target="asic"))
            with self.assertRaises(ValueError):
                config.allocation_from_config(self.values, state_report=self.report)
            allocation = config.allocation_from_config(self.values, state_report=self.report, target="generic")
            self.assertEqual(allocation["budget_used_bytes"], 80000)
            self.assertEqual(allocation["state_measurement"]["elaboration_target"], "generic")

    def test_vector_parallelism_changes_the_measurement_identity(self):
        narrow = {**self.values, "VECTOR_PE_COUNT": 8}
        wide = {**self.values, "VECTOR_PE_COUNT": 16}
        self.assertNotEqual(elaboration.identity(narrow, self.sources),
                            elaboration.identity(wide, self.sources))
        with patch.object(elaboration, "sources_sha256", return_value=self.sources):
            self.assertFalse(elaboration.current_report(narrow, self.report, target="generic"))
            altered = copy.deepcopy(self.report)
            altered["source_sha256"]["rtl/npu/top/npu_top.sv"] = "another-source"
            self.assertFalse(elaboration.current_report(wide, altered, target="generic"))

    def test_window_return_storage_follows_configured_parallelism(self):
        for bus_width, pe_count, response_bits in ((32, 8, 33), (64, 8, 65), (32, 16, 129), (64, 16, 129)):
            arrays = model.buffer_arrays_bits(4, 16, 12288, bus_width=bus_width,
                                              vector_pe_count=pe_count)
            self.assertEqual(arrays["conv_response_queue"], 2 * response_bits)
            self.assertEqual(arrays["conv_data_cache"], 4096 * 8)

    def test_prefetch_selected_port_has_target_specific_storage(self):
        asic = model.buffer_arrays_bits(4, 16, 12288, target="asic")
        generic = model.buffer_arrays_bits(4, 16, 12288, target="generic")
        self.assertEqual(generic["conv_prefetch_queue"] - asic["conv_prefetch_queue"], 8 * 64)

    def test_operand_storage_follows_parallel_input_rows(self):
        narrow = model.buffer_arrays_bits(4, 16, 12288, vector_pe_count=8)
        wide = model.buffer_arrays_bits(4, 16, 12288, vector_pe_count=16)
        self.assertEqual(wide["vector_buffers"] - narrow["vector_buffers"], 2 * 16 * 16)


if __name__ == "__main__":
    unittest.main()
