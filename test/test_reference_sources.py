#!/usr/bin/env python3
"""Verify exact reference access from an independently compacted Git repository."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from reference_sources import (ARCHIVE_ENV, ReferenceUnavailable, export_archive,
                               read_reference_file, resolve_reference, verify_archive)
import reference_sources


class ReferenceSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "original"
        self.delivery = self.directory / "delivery"
        self.archive = self.directory / "references"
        self.source.mkdir()
        self.git(self.source, "init", "--quiet")
        self.git(self.source, "config", "user.name", "Reference Test")
        self.git(self.source, "config", "user.email", "reference@example.invalid")
        (self.source / "rtl").mkdir()
        (self.source / "rtl/unit.sv").write_text("module unit; endmodule\n")
        (self.source / "rtl/support.svh").write_text("`define WIDTH 8\n")
        self.git(self.source, "add", "rtl")
        self.git(self.source, "commit", "--quiet", "-m", "Remote source")
        self.git(self.source, "branch", "remote_base")
        self.reference_bytes = "// 固定源码\nmodule unit(input logic a, output logic y); assign y = a; endmodule\n".encode()
        (self.source / "rtl/unit.sv").write_bytes(self.reference_bytes)
        self.git(self.source, "commit", "--quiet", "-am", "Intermediate source")
        self.revision = self.git(self.source, "rev-parse", "HEAD").strip()
        subprocess.run(["git", "clone", "--quiet", "--no-local", "--single-branch", "--depth", "1",
                        "--branch", "remote_base", str(self.source), str(self.delivery)], check=True)
        self.git(self.delivery, "config", "user.name", "Reference Test")
        self.git(self.delivery, "config", "user.email", "reference@example.invalid")
        (self.delivery / "rtl/unit.sv").write_text("module unit(input logic a, output logic y); assign y = !a; endmodule\n")
        self.git(self.delivery, "commit", "--quiet", "-am", "Delivery source")
        self.requests = {"references": {
            self.revision: ["rtl/unit.sv", "rtl/support.svh", "rtl/absent.sv"],
            self.revision[:8]: ["rtl/unit.sv"],
        }}
        self.summary = export_archive(self.source, self.requests, self.archive)

    def git(self, root, *arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments], text=True)

    def read(self, path="rtl/unit.sv", **arguments):
        return read_reference_file(self.delivery, self.revision, path,
                                   archive_root=self.archive, **arguments)

    def manifest(self):
        return json.loads((self.archive / "manifest.json").read_text())

    def save_manifest(self, value):
        (self.archive / "manifest.json").write_text(json.dumps(value))

    def test_independent_history_preserves_exact_reference_bytes(self):
        self.assertEqual(int(self.git(self.delivery, "rev-list", "--all", "--count")), 2)
        result = subprocess.run(["git", "-C", str(self.delivery), "cat-file", "-e", self.revision],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.read(), self.reference_bytes)
        self.assertEqual(self.read(text=True), self.reference_bytes.decode())
        self.assertEqual(read_reference_file(self.delivery, self.revision[:8], "rtl/unit.sv",
                         archive_root=self.archive), self.reference_bytes)
        self.assertEqual(read_reference_file(self.source, self.revision, "rtl/unit.sv"), self.reference_bytes)
        self.assertEqual(resolve_reference(self.source, self.revision[:8]), self.revision)
        self.assertEqual(resolve_reference(self.delivery, self.revision[:8], archive_root=self.archive), self.revision)
        self.assertEqual(self.summary["references"], 1)
        self.assertEqual(self.summary["unique_objects"], 2)

    def test_environment_selects_portable_archive(self):
        with patch.dict(os.environ, {ARCHIVE_ENV: str(self.archive)}):
            self.assertEqual(read_reference_file(self.delivery, self.revision, "rtl/unit.sv"), self.reference_bytes)

    def test_delivered_loader_reads_its_bundled_source_archive(self):
        test_root = self.delivery / "test"
        test_root.mkdir()
        shutil.copy2(reference_sources.__file__, test_root / "reference_sources.py")
        shutil.copytree(self.archive, test_root / "reference_sources/data")
        environment = dict(os.environ)
        environment.pop(ARCHIVE_ENV, None)
        command = ('import sys;sys.path.insert(0,sys.argv[1]);'
                   'from reference_sources import read_reference_file;'
                   'sys.stdout.buffer.write(read_reference_file(sys.argv[2],sys.argv[3],"rtl/unit.sv"))')
        actual = subprocess.check_output([sys.executable, "-c", command, str(test_root),
                                          str(self.delivery), self.revision], env=environment)
        self.assertEqual(actual, self.reference_bytes)

    def test_missing_source_differs_from_unsupplied_source(self):
        with self.assertRaises(FileNotFoundError):
            self.read("rtl/absent.sv")
        with self.assertRaises(ReferenceUnavailable):
            self.read("rtl/not_archived.sv")

    def test_changed_compressed_object_is_rejected(self):
        manifest = self.manifest()
        checksum = manifest["references"][self.revision]["files"]["rtl/unit.sv"]["sha256"]
        path = self.archive / "objects" / (checksum + ".gz")
        path.write_bytes(path.read_bytes() + b"modified")
        with self.assertRaises(ValueError):
            self.read()

    def test_changed_git_blob_identifier_is_rejected(self):
        manifest = self.manifest()
        manifest["references"][self.revision]["files"]["rtl/unit.sv"]["git_blob"] = "0" * 40
        self.save_manifest(manifest)
        with self.assertRaises(ValueError):
            self.read()

    def test_ambiguous_revision_is_rejected(self):
        manifest = self.manifest()
        other = self.revision[:7] + ("0" if self.revision[7] != "0" else "1") + self.revision[8:]
        manifest["references"][other] = manifest["references"][self.revision]
        self.save_manifest(manifest)
        with self.assertRaises(ReferenceUnavailable):
            read_reference_file(self.delivery, self.revision[:7], "rtl/unit.sv", archive_root=self.archive)

    def test_paths_and_object_links_cannot_leave_archive(self):
        for path in ("../unit.sv", "/rtl/unit.sv", "rtl//unit.sv", "rtl/./unit.sv"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.read(path)
        manifest = self.manifest()
        checksum = manifest["references"][self.revision]["files"]["rtl/unit.sv"]["sha256"]
        path = self.archive / "objects" / (checksum + ".gz")
        outside = self.directory / "outside.gz"
        path.rename(outside)
        path.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.read()

    def test_complete_archive_verification(self):
        self.assertEqual(verify_archive(self.archive), self.summary)
        self.assertEqual(self.summary["present_files"], 2)
        self.assertEqual(self.summary["absent_files"], 1)


if __name__ == "__main__":
    unittest.main()
