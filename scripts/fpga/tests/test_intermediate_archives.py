#!/usr/bin/env python3
"""检查压缩恢复的内容完整性和已有文件保护。"""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from manage_intermediate_archives import archive_file, relative_path, restore_file


class ArchiveTests(unittest.TestCase):
    def test_round_trip_and_existing_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'pre_lut.il'
            content = bytes(range(256)) * 4096
            source.write_bytes(content)
            manifest = {'files': {}}
            entry = archive_file(root, Path('pre_lut.il'), manifest, root / 'manifest.json')
            self.assertFalse(source.exists())
            self.assertEqual(entry['uncompressed_sha256'], hashlib.sha256(content).hexdigest())
            restore_file(root, Path('pre_lut.il'), entry)
            self.assertEqual(source.read_bytes(), content)
            restore_file(root, Path('pre_lut.il'), entry)
            source.write_bytes(b'new user content')
            with self.assertRaises(FileExistsError):
                restore_file(root, Path('pre_lut.il'), entry)
            self.assertEqual(source.read_bytes(), b'new user content')

    def test_archive_checksum_and_expected_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'netlist.json'
            source.write_bytes(b'data' * 1000)
            entry = archive_file(root, Path(source.name), {'files': {}}, root / 'manifest.json')
            changed = copy.deepcopy(entry)
            changed['uncompressed_sha256'] = '0' * 64
            with self.assertRaises(ValueError):
                restore_file(root, Path(source.name), changed)
            self.assertFalse(source.exists())
            self.assertFalse(source.with_suffix('.json.restore.tmp').exists())
            (root / entry['archive']).write_bytes(b'invalid archive')
            with self.assertRaises(ValueError):
                restore_file(root, Path(source.name), entry)
            self.assertFalse(source.exists())

    def test_root_boundary_and_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError):
                relative_path(root, '../other')
            (root / 'link').symlink_to(root / 'target')
            with self.assertRaises(ValueError):
                relative_path(root, 'link')


if __name__ == '__main__':
    unittest.main()
