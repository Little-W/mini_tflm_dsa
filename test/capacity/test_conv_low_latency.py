"""Check convolution profile selection across configuration and build paths."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config, elaboration, model


class ConvLowLatencyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="conv_profile_")
        self.work = Path(self.directory.name)
        self.config = self.work / "npu.mk"
        self.config.write_text((ROOT / "config/npu.mk").read_text())
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {"NPU_CONFIG", "CONV_LOW_LATENCY", "MAKEFLAGS", "MFLAGS"}}

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

    def test_default_and_rejected_configuration_values(self):
        self.assertEqual(config.DEFAULTS["CONV_LOW_LATENCY"], 0)
        for value in (-1, 2, True, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                config.validate_config(dict(config.DEFAULTS, CONV_LOW_LATENCY=value))

    def test_capacity_identity_and_queue_storage(self):
        default = dict(config.DEFAULTS, CONV_LOW_LATENCY=0)
        direct = dict(config.DEFAULTS, CONV_LOW_LATENCY=1)
        self.assertNotEqual(elaboration.identity(default, {"source": "a"}),
                            elaboration.identity(direct, {"source": "a"}))
        arrays = [model.buffer_arrays_bits(4, 16, 12288, conv_low_latency=mode)
                  for mode in (False, True)]
        self.assertEqual(arrays[0]["conv_request_queue"], 2 * arrays[1]["conv_request_queue"])
        self.assertEqual(arrays[0]["conv_response_queue"], 2 * arrays[1]["conv_response_queue"])
        self.assertEqual(arrays[0]["conv_data_cache"], arrays[1]["conv_data_cache"])

    def test_unit_and_python_build_arguments(self):
        for mode in (0, 1):
            with self.subTest(mode=mode):
                value = f"CONV_LOW_LATENCY={mode}"
                text = self.make(".", "-n", "vcs-unit-build", "UNIT=npu_top", value)
                self.assertIn(f"TB_CONV_LOW_LATENCY={mode}", text)
                self.assertIn(f"_cll{mode}", text)
                self.assertIn(f"--set '{value}'", text)
                text = self.make(".", "-n", "pcr-backend", value)
                self.assertIn(f"--conv-low-latency '{mode}'", text)

    def test_soc_hardware_firmware_and_build_identity(self):
        extra = ("inspect-profile:\n"
                 "\t@$(info HW=$(MMA_PARAM_OPTS))\n"
                 "\t@$(info FW=$(SOC_HW_DEFINES))\n"
                 "\t@$(info BIN=$(SIMV))\n\t@:\n")
        for mode in (0, 1):
            text = self.make("veri/sim", "inspect-profile", f"CONV_LOW_LATENCY={mode}", extra=extra)
            self.assertIn(f"-pvalue+tb_top.DUT_CONV_LOW_LATENCY={mode}", text)
            self.assertIn(f"-DNPU_CONFIG_CONV_LOW_LATENCY={mode}", text)
            self.assertIn(f"_CLL{mode}", text)

    def test_asic_parameter_and_build_identity(self):
        extra = "inspect-profile:\n\t@$(info HW=$(DESIGN_PARAMETERS))\n\t@$(info OUT=$(PROJ_TEMP))\n\t@:\n"
        for mode in (0, 1):
            text = self.make("asic/synthesis", "inspect-profile", f"CONV_LOW_LATENCY={mode}", extra=extra)
            self.assertIn(f"CONV_LOW_LATENCY={mode}", text)
            self.assertIn(f"_cll{mode}", text)

    def test_python_backend_reads_profile(self):
        for mode in (0, 1):
            result = subprocess.run([sys.executable, str(ROOT / "veri/python_model/build_backend.py"),
                                     "--config", str(self.config), "--conv-low-latency", str(mode),
                                     "--print-config"], env=self.environment, capture_output=True,
                                    text=True, timeout=30, check=True)
            parameters = json.loads(result.stdout)
            self.assertEqual(parameters["conv_low_latency"], mode)
            self.assertIn(f"_cll{mode}", parameters["tag"])


if __name__ == "__main__":
    unittest.main()
