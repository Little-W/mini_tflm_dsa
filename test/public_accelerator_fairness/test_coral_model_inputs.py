#!/usr/bin/env python3
"""Check source, runtime, object integrity and path bounds before model linking."""
import gzip
import hashlib
import json
from pathlib import Path
import platform
import tempfile
from types import SimpleNamespace
import unittest

from run_coral_fair import ARCHIVE_SHA, CORAL_COMMIT, input_path, portable_model


def digest(data):
    return hashlib.sha256(data).hexdigest()


class PortableModelTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = SimpleNamespace(model_inputs=self.root / "model",
                                    comparison_root=self.root / "comparison",
                                    reference_root=self.root / "reference")
        self.args.model_inputs.mkdir()
        self.sources = {}
        for relative in ("coral/rtl/VmeCoreMiniAxi.sv", "coral/rtl/vme_observation.vlt",
                         "coral/upstream/hdl/verilog/sram_backdoor.cc",
                         "coral/upstream/hdl/verilog/sram_backdoor.h",
                         "coral/benchmark/shared_gemm_staged.elf"):
            path = self.args.comparison_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = relative.encode()
            path.write_bytes(data)
            self.sources[relative] = digest(data)
        (self.args.comparison_root / "coral/UPSTREAM.json").write_text(json.dumps({
            "commit": CORAL_COMMIT,
            "generated_rtl_sha256": self.sources["coral/rtl/VmeCoreMiniAxi.sv"]}))
        runtime_hashes = {}
        for name in ("verilated.h", "verilated_dpi.h", "verilated_threads.h"):
            path = self.args.reference_root / "tools/verilator/include" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
            runtime_hashes[name] = digest(name.encode())
        names = ("VVmeCoreMiniAxi__ALL.a", "verilated.o", "verilated_dpi.o",
                 "verilated_threads.o", "sram_backdoor.o", "V0.h", "V1.h", "V2.h", "V3.h", "V4.h")
        files = {}
        for name in names:
            content = name.encode()
            compressed = gzip.compress(content, mtime=0)
            (self.args.model_inputs / (name + ".gz")).write_bytes(compressed)
            files[name] = {"compressed_sha256": digest(compressed), "compressed_bytes": len(compressed),
                           "uncompressed_sha256": digest(content), "uncompressed_bytes": len(content)}
        (self.args.model_inputs / "provenance.json").write_bytes(b"{}")
        self.manifest = {"format_version": 1, "source_commit": CORAL_COMMIT,
                         "source_archive_sha256": ARCHIVE_SHA,
                         "verilator": "Verilator 5.054 2026-11-01 rev v5.054",
                         "platform": {"system": platform.system(), "machine": platform.machine()},
                         "comparison_source_sha256": self.sources,
                         "runtime_headers_sha256": runtime_hashes,
                         "provenance_files_sha256": {"provenance.json": digest(b"{}")},
                         "files": files}
        (self.args.model_inputs / "model_inputs.json").write_text(json.dumps(self.manifest))

    def test_complete_input_validation(self):
        _, manifest, checked = portable_model(self.args)
        self.assertEqual(manifest["files"], self.manifest["files"])
        self.assertEqual(len(checked), 8)

    def test_changed_source_is_rejected(self):
        (self.args.comparison_root / "coral/rtl/VmeCoreMiniAxi.sv").write_bytes(b"changed")
        with self.assertRaises(AssertionError):
            portable_model(self.args)

    def test_changed_runtime_is_rejected(self):
        (self.args.reference_root / "tools/verilator/include/verilated.h").write_bytes(b"changed")
        with self.assertRaises(AssertionError):
            portable_model(self.args)

    def test_changed_model_object_is_rejected(self):
        path = self.args.model_inputs / "VVmeCoreMiniAxi__ALL.a.gz"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(AssertionError):
            portable_model(self.args)

    def test_paths_cannot_leave_input_root(self):
        for relative in ("../outside", str(self.root / "absolute")):
            with self.assertRaises(ValueError):
                input_path(self.args.model_inputs, relative)
        (self.args.model_inputs / "outside_link").symlink_to(self.root)
        with self.assertRaises(ValueError):
            input_path(self.args.model_inputs, "outside_link/file")


if __name__ == "__main__":
    unittest.main()
