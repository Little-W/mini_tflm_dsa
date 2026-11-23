"""使用实际模型目录检查 IA 存储配置对应的后端选择。"""
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import config

spec = importlib.util.spec_from_file_location("npu_backend_selection_runtime", ROOT / "veri/python_model/runtime.py")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


class BackendSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.here = self.root / "veri/python_model"
        self.configuration = self.root / "npu.mk"
        self.configuration.write_text("IA_COMPACT_ENABLE ?= 0\n")
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in {*config.DEFAULTS, "NPU_CONFIG"}}
        self.environment["NPU_CONFIG"] = str(self.configuration)
        self.cfg = [0] * 32
        self.cfg[1], self.cfg[2], self.cfg[9], self.cfg[11] = 16, 4, 16, 64

    def tearDown(self):
        self.temporary.cleanup()

    def backend(self, name, compact):
        directory = self.here / "backends" / name
        directory.mkdir(parents=True)
        values = config.DEFAULTS
        manifest = dict(size=16, ia_cache_blocks=4, ps_frame_count=16,
                        bus_width=values["NPU_AXI_DATA_WIDTH"], ps_compress=bool(values["PCR_ENGINE"]),
                        force_raw=bool(values["PS_FORCE_RAW"]), shared_bank_bytes=values["SHARED_BANK_BYTES"],
                        shared_physical_banks=values["SHARED_BANK_COUNT"], mem_words=64)
        if compact is not None:
            manifest["ia_compact_enable"] = compact
        (directory / "manifest.json").write_text(json.dumps(manifest))
        (directory / "rtl_server").write_text("")
        return directory

    def select(self, compact):
        with patch.object(runtime, "HERE", self.here), patch.object(runtime, "ROOT", self.root), \
                patch.dict(os.environ, {**self.environment, "IA_COMPACT_ENABLE": str(compact)}, clear=True):
            return runtime.select_backend(self.cfg)

    def test_selects_matching_storage_configuration(self):
        directories = {value: self.backend(f"storage_{value}", value) for value in (0, 1)}
        for value in (0, 1):
            self.assertEqual(self.select(value), directories[value])

    def test_rejects_other_storage_configuration(self):
        self.backend("storage_1", 1)
        with self.assertRaises(FileNotFoundError):
            self.select(0)

    def test_requires_explicit_storage_configuration(self):
        self.backend("unspecified_storage", None)
        for value in (0, 1):
            with self.assertRaises(FileNotFoundError):
                self.select(value)


if __name__ == "__main__":
    unittest.main()
