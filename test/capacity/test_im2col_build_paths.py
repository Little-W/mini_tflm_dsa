"""Check expanded hardware and firmware parameters from the selected config."""
from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Im2colBuildPathsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="im2col_build_")
        self.work = Path(self.temporary.name)
        self.config = self.work / "npu.mk"
        self.config.write_text(re.sub(r"(?m)^IM2COL_CACHE_BYTES.*$",
                                      "IM2COL_CACHE_BYTES ?= 8192",
                                      (ROOT / "config/npu.mk").read_text()))
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {"NPU_CONFIG", "IM2COL_CACHE_BYTES",
                                           "NPU_AXI_DATA_WIDTH", "SHARED_BANK_BYTES",
                                           "SHARED_BANK_COUNT", "MAKEFLAGS", "MFLAGS"}}

    def tearDown(self):
        self.temporary.cleanup()

    def make(self, directory, *arguments, extra=None):
        command = ["make", "--no-print-directory", "-C", str(ROOT / directory),
                   f"NPU_CONFIG={self.config}"]
        if extra:
            definitions = self.work / "inspect.mk"
            definitions.write_text(".RECIPEPREFIX :=\n" + extra)
            command += ["-f", "Makefile", "-f", str(definitions)]
        result = subprocess.run(command + list(arguments), env=self.environment,
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_unit_build_selects_capacity_and_separate_output(self):
        for capacity in (8192, 16384):
            with self.subTest(capacity=capacity):
                text = self.make(".", "-n", "vcs-unit-build", "UNIT=npu_top",
                                 f"IM2COL_CACHE_BYTES={capacity}")
                self.assertIn(f"+TB_IM2COL_CACHE_BYTES={capacity}", text)
                self.assertIn(f"_im2col{capacity}", text)
                self.assertIn(f"--set 'IM2COL_CACHE_BYTES={capacity}'", text)

    def test_soc_hardware_firmware_and_output_identity(self):
        extra = ("inspect-im2col:\n"
                 "\t@$(info HW=$(MMA_PARAM_OPTS))\n"
                 "\t@$(info FW=$(SOC_HW_DEFINES))\n"
                 "\t@$(info BIN=$(SIMV))\n"
                 "\t@$(info TAG=$(PCR_CONFIG_TAG))\n"
                 "\t@:\n")
        for capacity in (8192, 32768):
            with self.subTest(capacity=capacity):
                text = self.make("veri/sim", "inspect-im2col",
                                 f"IM2COL_CACHE_BYTES={capacity}", extra=extra)
                self.assertIn(f"-pvalue+tb_top.DUT_IM2COL_CACHE_BYTES={capacity}", text)
                self.assertIn(f"-DNPU_CONFIG_IM2COL_CACHE_BYTES={capacity}", text)
                self.assertEqual(text.count(f"_IM2COL{capacity}"), 2)

    def test_asic_hardware_and_output_identity(self):
        extra = ("inspect-im2col:\n"
                 "\t@$(info PARAMS=$(DESIGN_PARAMETERS))\n"
                 "\t@$(info OUTPUT=$(PROJ_TEMP))\n"
                 "\t@:\n")
        text = self.make("asic/synthesis", "inspect-im2col",
                         "IM2COL_CACHE_BYTES=16384", extra=extra)
        self.assertIn("IM2COL_CACHE_BYTES=16384", text)
        self.assertIn("_im2col16384", text)

    def test_python_backend_receives_selected_capacity(self):
        text = self.make(".", "-n", "pcr-backend", "IM2COL_CACHE_BYTES=32768")
        self.assertIn("--im2col-cache-bytes '32768'", text)

    def test_conv_default_sets_follow_config_and_can_be_overridden(self):
        text = self.make(".", "-n", "conv-npu")
        self.assertIn("--cache-sets 256", text)
        text = self.make(".", "-n", "conv-npu", "CONV_CACHE_SETS=64")
        self.assertIn("--cache-sets 64", text)


if __name__ == "__main__":
    unittest.main()
