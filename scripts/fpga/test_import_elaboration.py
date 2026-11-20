#!/usr/bin/env python3
"""Check source agreement and saved-file integrity before reusing elaboration."""
import json
from pathlib import Path
import tempfile
import unittest

from open_fpga_synth import digest, import_elaboration, import_pre_alu


class ImportElaborationTests(unittest.TestCase):
    def prepare(self, root):
        source, target = root / 'source', root / 'target'
        source.mkdir()
        target.mkdir()
        manifest = {'top': 'soc_top', 'sources_sha256': {'design.sv': '123'}, 'parameters': {'SIZE': 16}}
        (source / 'manifest.json').write_text(json.dumps(manifest))
        (source / 'elaborated.il').write_text('module \\soc_top\nend\n')
        (source / 'stages.json').write_text(json.dumps({'01_elaborate': {
            'output_sha256': digest(source / 'elaborated.il'), 'elapsed_seconds': 1.0}}))
        return source, target, manifest

    def test_identical_inputs_are_imported_with_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest = self.prepare(Path(temporary))
            result = import_elaboration(source, target, {**manifest, 'wide_alu_mapping': {'budget': 740}}, target / '01.ys')
            self.assertEqual(result['imported_from'], str(source))
            self.assertEqual(digest(source / 'elaborated.il'), digest(target / 'elaborated.il'))
            self.assertEqual(result['source_stage']['elapsed_seconds'], 1.0)

    def test_different_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest = self.prepare(Path(temporary))
            manifest['sources_sha256']['design.sv'] = '456'
            with self.assertRaises(RuntimeError):
                import_elaboration(source, target, manifest, target / '01.ys')

    def test_modified_checkpoint_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest = self.prepare(Path(temporary))
            (source / 'elaborated.il').write_text('changed')
            with self.assertRaises(RuntimeError):
                import_elaboration(source, target, manifest, target / '01.ys')

    def prepare_arithmetic(self, root):
        source, target, manifest = self.prepare(root)
        (source / 'pre_alu.json').write_text('{"modules":{}}\n')
        script = target / '02a_pre_alu.ys'
        for folder in (source, target):
            (folder / script.name).write_text(f'read_rtlil {folder}/elaborated.il\nsynth_xilinx -run begin:fine\nwrite_json {folder}/pre_alu.json\n')
        stages = json.loads((source / 'stages.json').read_text())
        stages['02a_pre_alu'] = {'output_sha256': digest(source / 'pre_alu.json'),
                               'script_sha256': digest(source / script.name), 'elapsed_seconds': 5.0}
        (source / 'stages.json').write_text(json.dumps(stages))
        return source, target, manifest, script

    def test_arithmetic_reuse_preserves_file_and_stage(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest, script = self.prepare_arithmetic(Path(temporary))
            result = import_pre_alu(source, target, manifest, script)
            self.assertEqual(digest(source / 'pre_alu.json'), digest(target / 'pre_alu.json'))
            self.assertEqual(result['source_stage']['elapsed_seconds'], 5.0)

    def test_arithmetic_rejects_changed_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest, script = self.prepare_arithmetic(Path(temporary))
            script.write_text(script.read_text() + 'opt\n')
            with self.assertRaises(RuntimeError):
                import_pre_alu(source, target, manifest, script)

    def test_arithmetic_rejects_changed_netlist(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest, script = self.prepare_arithmetic(Path(temporary))
            (source / 'pre_alu.json').write_text('changed')
            with self.assertRaises(RuntimeError):
                import_pre_alu(source, target, manifest, script)

    def test_arithmetic_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, target, manifest, script = self.prepare_arithmetic(Path(temporary))
            manifest['sources_sha256']['design.sv'] = '456'
            with self.assertRaises(RuntimeError):
                import_pre_alu(source, target, manifest, script)


if __name__ == '__main__':
    unittest.main()
