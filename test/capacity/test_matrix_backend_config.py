"""检查完整矩阵模型构建入口的阵列和共享存储要求。"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity.config import DEFAULTS


class MatrixBackendConfigurationTests(unittest.TestCase):
    def run_builder(self, arguments, output):
        environment = {key: value for key, value in os.environ.items()
                       if key not in {*DEFAULTS, "NPU_CONFIG"}}
        return subprocess.run(
            [sys.executable, str(ROOT / "veri/python_model/build_backend.py"),
             "--config", str(ROOT / "config/npu.mk"), "--output-root", str(output),
             "--verilator", str(output / "compiler_must_not_start"), *arguments],
            env=environment, text=True, capture_output=True, timeout=30)

    def test_explicit_shared_banks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            for banks in (6, 7, 8, 9):
                run = self.run_builder(["--size", "16", "--ps-compress", "--shared-bank-bytes", "2048",
                                        "--shared-bank-count", str(banks), "--print-config"], output)
                self.assertEqual(run.returncode, 0, run.stderr)
                values = json.loads(run.stdout)
                self.assertTrue(values["shared_enabled"])
                self.assertEqual(values["shared_physical_banks"], banks)
                self.assertFalse(output.exists())

    def test_automatic_shared_banks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            run = self.run_builder(["--size", "16", "--cache", "4", "--ps-compress",
                                    "--shared-bank-count", "0", "--shared-bank-bytes", "2048",
                                    "--ps-pool-bytes", "12288", "--print-config"], output)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(json.loads(run.stdout)["shared_physical_banks"], 7)

    def test_unsupported_matrix_modes_stop_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            for arguments in (["--size", "4"], ["--size", "8"],
                              ["--size", "16", "--no-ps-compress", "--no-force-raw"]):
                run = self.run_builder(arguments, output)
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn("matrix backend requires SIZE=16", run.stderr)
                self.assertFalse(output.exists())

    def test_incomplete_shared_layout_stops_before_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            run = self.run_builder(["--size", "16", "--cache", "2", "--ps-compress",
                                    "--shared-bank-count", "0", "--shared-bank-bytes", "2048",
                                    "--ps-pool-bytes", "64"], output)
            self.assertEqual(run.returncode, 2, run.stderr)
            self.assertIn("6 to 9 complete shared memory banks", run.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
