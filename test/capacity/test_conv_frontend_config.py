"""Check the convolution frontend capacity and its build configuration."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration, im2col_cache, model


class ConvFrontendConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="conv_frontend_config_")
        self.work = Path(self.directory.name)
        self.config = self.work / "npu.mk"
        self.config.write_text((ROOT / "config/npu.mk").read_text())
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {"NPU_CONFIG", "MAKEFLAGS", "MFLAGS"}}

    def tearDown(self):
        self.directory.cleanup()

    def make(self, directory, *arguments, extra=None):
        command = ["make", "--no-print-directory", "-C", str(ROOT / directory),
                   f"NPU_CONFIG={self.config}"]
        if extra:
            added = self.work / "inspect.mk"
            added.write_text(".RECIPEPREFIX :=\n" + extra)
            command += ["-f", "Makefile", "-f", str(added)]
        result = subprocess.run(command + list(arguments), env=self.environment,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_single_request_and_response_capacity(self):
        for cache_bytes in (512, 4096, 16384):
            with self.subTest(cache_bytes=cache_bytes):
                allocation = model.allocation(4, 16, 12288, 131072,
                    im2col_cache_bytes=cache_bytes, bus_width=64, vector_pe_count=16)
                arrays = allocation["buffer_arrays_bits"]
                sets = im2col_cache.geometry(cache_bytes)["sets"]
                self.assertEqual(arrays["conv_request_queue"], 128 + (sets - 1).bit_length() + 3)
                self.assertEqual(arrays["conv_response_queue"], 128 + 1)
                self.assertEqual(arrays["conv_data_cache"], cache_bytes * 8)
                self.assertEqual(allocation["conv_request_response_depth"], 1)

    def test_capacity_identity_tracks_frontend_geometry(self):
        small = dict(config.DEFAULTS, IM2COL_CACHE_BYTES=4096)
        large = dict(config.DEFAULTS, IM2COL_CACHE_BYTES=16384)
        self.assertNotEqual(elaboration.identity(small, {"source": "a"}),
                            elaboration.identity(large, {"source": "a"}))
        self.assertEqual(elaboration.hardware_config(large)["IM2COL_CACHE_BYTES"], 16384)

    def test_unit_and_python_build_arguments(self):
        text = self.make(".", "-n", "vcs-unit-build", "UNIT=npu_top", "IM2COL_CACHE_BYTES=16384")
        self.assertIn("TB_IM2COL_CACHE_BYTES=16384", text)
        self.assertIn("_im2col16384", text)
        self.assertIn("--set 'IM2COL_CACHE_BYTES=16384'", text)
        text = self.make(".", "-n", "pcr-backend", "IM2COL_CACHE_BYTES=16384")
        self.assertIn("--im2col-cache-bytes '16384'", text)

    def test_soc_hardware_firmware_and_build_identity(self):
        extra = ("inspect-profile:\n"
                 "\t@$(info HW=$(MMA_PARAM_OPTS))\n"
                 "\t@$(info FW=$(SOC_HW_DEFINES))\n"
                 "\t@$(info BIN=$(SIMV))\n\t@:\n")
        text = self.make("veri/sim", "inspect-profile", "IM2COL_CACHE_BYTES=16384", extra=extra)
        self.assertIn("-pvalue+tb_top.DUT_IM2COL_CACHE_BYTES=16384", text)
        self.assertIn("-DNPU_CONFIG_IM2COL_CACHE_BYTES=16384", text)
        self.assertIn("_IM2COL16384", text)

    def test_asic_parameter_and_build_identity(self):
        extra = "inspect-profile:\n\t@$(info HW=$(DESIGN_PARAMETERS))\n\t@$(info OUT=$(PROJ_TEMP))\n\t@:\n"
        text = self.make("asic/synthesis", "inspect-profile", "IM2COL_CACHE_BYTES=16384", extra=extra)
        self.assertIn("IM2COL_CACHE_BYTES=16384", text)
        self.assertIn("_im2col16384", text)

    def test_python_backend_reads_frontend_geometry(self):
        result = subprocess.run([sys.executable, str(ROOT / "veri/python_model/build_backend.py"),
                                 "--config", str(self.config), "--im2col-cache-bytes", "16384",
                                 "--print-config"], env=self.environment, capture_output=True,
                                text=True, timeout=30, check=True)
        parameters = json.loads(result.stdout)
        self.assertEqual(parameters["im2col_cache_bytes"], 16384)
        self.assertIn("_im2col16384", parameters["tag"])


if __name__ == "__main__":
    unittest.main()
