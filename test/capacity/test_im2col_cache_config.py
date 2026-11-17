"""Configurable im2col storage and spatial-set capacity checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, im2col_cache, menuconfig, model
from scripts.capacity.menuconfig_state import MenuConfigState


class Im2colCacheConfiguration(unittest.TestCase):
    def test_supported_capacity_geometry_and_buffer_cost(self):
        previous = None
        for capacity in im2col_cache.BYTE_CHOICES:
            values = config.validate_config({**config.DEFAULTS, "IM2COL_CACHE_BYTES": capacity},
                                            check_budget=False)
            self.assertEqual(values["IM2COL_CACHE_BYTES"], capacity)
            geometry = im2col_cache.geometry(capacity)
            self.assertEqual(geometry["sets"] * 2 * 16, capacity)
            self.assertEqual(geometry["metadata_bits"], capacity // 16 * 75)
            arrays = model.buffer_arrays_bits(4, 16, 12288, bank_count=7,
                                               im2col_cache_bytes=capacity)
            self.assertEqual(arrays["conv_data_cache"], capacity * 8)
            self.assertEqual(arrays["conv_cache_metadata"], capacity // 16 * 75)
            if previous is not None:
                old_capacity, old_arrays = previous
                self.assertEqual(sum(arrays.values()) - sum(old_arrays.values()),
                                 (capacity - old_capacity) // 16 * (128 + 75))
            previous = capacity, arrays

    def test_invalid_capacities(self):
        for value in (0, 16, 256, 768, 1023, 65537, 131072, True, 4096.0, "4096"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate_config({**config.DEFAULTS, "IM2COL_CACHE_BYTES": value},
                                       check_budget=False)

    def test_environment_overrides_and_header(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "npu.mk"
            path.write_text("IM2COL_CACHE_BYTES ?= 2048\n")
            with patch.dict(os.environ, {"IM2COL_CACHE_BYTES": "8192"}):
                values = config.selected_config(path)
                self.assertEqual(values["IM2COL_CACHE_BYTES"], 8192)
            values = {**config.DEFAULTS, **config.read_config(path)}
            self.assertIn("#define NPU_CONFIG_IM2COL_CACHE_BYTES 2048", config.emit_c_header(values))

    def test_menu_saves_capacity_and_displays_size_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "npu.mk"
            state = MenuConfigState(path)
            state.set_value("IM2COL_CACHE_BYTES", "8 KiB")
            self.assertEqual(state.values["IM2COL_CACHE_BYTES"], 8192)
            state.save()
            self.assertEqual(config.read_config(path)["IM2COL_CACHE_BYTES"], 8192)
        field = next(item for item in menuconfig.FIELDS if item.key == "IM2COL_CACHE_BYTES")
        self.assertTrue(field.byte_size)
        self.assertEqual(field.choices, im2col_cache.BYTE_CHOICES)
        help_text = im2col_cache.help_text(4096)
        self.assertIn("128 sets", help_text)
        self.assertIn("85 / 42", help_text)
        self.assertIn("2400 B", help_text)

    def test_capacity_show_reads_selected_cache(self):
        command = [sys.executable, str(ROOT / "scripts/capacity/solve.py"),
                   "--config", str(ROOT / "config/npu.mk"), "--show",
                   "--set", "IM2COL_CACHE_BYTES=8192"]
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True)
        value = json.loads(result.stdout)
        self.assertEqual(value["allocation"]["im2col_cache_geometry"]["data_bytes"], 8192)
        self.assertEqual(value["im2col_cache_guidance"]["band_width_limits"][0],
                         dict(kernel=3, effective_kernel_h=3,
                              s8_k16_max_input_width=170, s16_k16_max_input_width=85))

    def test_solver_preserves_cache_in_budget(self):
        tasks = [dict(M=64, K=64, N=64)]
        result = model.solve(tasks, 131072, bank_bytes=2048, im2col_cache_bytes=16384)
        allocation = result["allocation"]
        self.assertEqual(allocation["im2col_cache_geometry"]["data_bytes"], 16384)
        self.assertEqual(allocation["buffer_arrays_bits"]["conv_data_cache"], 16384 * 8)
        self.assertLessEqual(allocation["buffer_ram_bytes"], 131072)
        with self.assertRaises(ValueError):
            model.solve(tasks, 32768, bank_bytes=2048, im2col_cache_bytes=32768)


class Im2colWorkingSetGuidance(unittest.TestCase):
    @staticmethod
    def analyze(capacity=4096, **overrides):
        arguments = dict(input_h=64, input_w=64, input_channels=16,
                         kernel_h=3, kernel_w=3)
        arguments.update(overrides)
        return im2col_cache.analyze_convolution(capacity, **arguments)

    def test_band_sizes_and_data_width(self):
        self.assertTrue(self.analyze()["band_fits"])
        self.assertFalse(self.analyze(2048)["band_fits"])
        self.assertEqual(self.analyze(2048)["recommended_cache_bytes"], 4096)
        wide = self.analyze(element_bytes=2)
        self.assertEqual(wide["band_peak_lines_per_set"], 4)
        self.assertEqual(wide["recommended_cache_bytes"], 8192)
        self.assertTrue(self.analyze(input_w=32, element_bytes=2)["band_fits"])
        dilated = self.analyze(dilation_h=2)
        self.assertEqual(dilated["effective_kernel_h"], 5)
        self.assertEqual(dilated["recommended_cache_bytes"], 8192)

    def test_tensor_capacity_and_fragment_prefetch_have_separate_conditions(self):
        fragmented = self.analyze(input_h=10, input_w=10, input_channels=64)
        self.assertFalse(fragmented["whole_tensor_data_capacity_fits"])
        self.assertTrue(fragmented["next_s8_fragment_spatial_condition"])
        fitting = self.analyze(8192, input_h=2, input_w=256)
        self.assertTrue(fitting["whole_tensor_data_capacity_fits"])
        self.assertFalse(fitting["next_s8_fragment_spatial_condition"])

    def test_index_eligibility(self):
        for overrides in (dict(input_channels=3), dict(input_base_mod16=8)):
            result = self.analyze(**overrides)
            self.assertFalse(result["spatial_index_eligible"])
            self.assertIsNone(result["band_fits"])
            self.assertIsNone(result["recommended_cache_bytes"])

    def test_band_occupancy_against_enumerated_spatial_sets(self):
        for capacity in (512, 2048, 4096, 8192):
            sets = capacity // 32
            for width in (7, 16, 31, 32, 63, 64, 85):
                for height in (1, 3, 5):
                    for element in (1, 2):
                        channels = 16
                        result = self.analyze(capacity, input_w=width,
                                              kernel_h=height, element_bytes=element)
                        for first_pixel in (0, width, sets - 1):
                            count = [0] * sets
                            for pixel in range(first_pixel, first_pixel + width * height):
                                count[pixel % sets] += element
                            self.assertEqual(result["band_peak_lines_per_set"], max(count))

    def test_packed_small_pixels_include_row_start(self):
        for capacity in (512, 2048, 4096):
            sets = capacity // 32
            for width in (7, 16, 31, 64):
                for pixel_bytes in (1, 2, 4, 8):
                    result = self.analyze(capacity, input_w=width, input_channels=pixel_bytes)
                    peak = 0
                    for first_row in range(16):
                        start = first_row * width * pixel_bytes
                        end = (first_row + 3) * width * pixel_bytes
                        counts = [0] * sets
                        for line in range(start // 16, (end + 15) // 16):
                            counts[line % sets] += 1
                        peak = max(peak, max(counts))
                    self.assertEqual(result["band_peak_lines_per_set"], peak)


if __name__ == "__main__":
    unittest.main()
