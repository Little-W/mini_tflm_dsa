"""检查容量测试入口的源码确认、程序复用和观察器来源记录。"""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import run_npu as entry


class CapacityRunnerTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sim = self.root/'sim'
        self.binary = self.sim/'obj/Vtb_conv_npu'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b'capacity-test-program')
        self.manifest = {
            'returncode': 0, 'size': 16, 'bus_width': 64,
            'shared_bank_bytes': 8192, 'shared_bank_count': 7,
            'ps_compress': True, 'force_raw': True, 'pool_bytes': 49152,
            'binary_sha256': entry.digest(self.binary),
            'source_sha256': {name: entry.digest(entry.ROOT/name)
                              for name in entry.CAPACITY_SOURCES},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.sim/'build.json').write_text(json.dumps(self.manifest))

    def test_current_program_and_three_sources(self):
        binary, _ = entry.validated_simulator(self.sim, 64, True)
        self.assertEqual(binary, self.binary)
        for relative in entry.CAPACITY_SOURCES:
            with self.subTest(source=relative):
                expected = self.manifest['source_sha256'][relative]
                self.manifest['source_sha256'][relative] = '0'*64
                self.write_manifest()
                with self.assertRaisesRegex(RuntimeError, 'capacity RTL differs'):
                    entry.validated_simulator(self.sim, 64, True)
                self.manifest['source_sha256'][relative] = expected

    def test_reference_program_uses_its_recorded_sources(self):
        self.manifest['source_sha256'] = {'rtl/npu/top/npu_top.sv': '1'*64}
        self.write_manifest()
        _, manifest = entry.validated_simulator(self.sim, 64, False)
        self.assertEqual(manifest['source_sha256'], self.manifest['source_sha256'])

    def test_program_integrity_and_bus_width(self):
        with self.assertRaisesRegex(RuntimeError, 'bus_width'):
            entry.validated_simulator(self.sim, 32, True)
        self.binary.write_bytes(b'changed-program')
        with self.assertRaisesRegex(RuntimeError, 'executable differs'):
            entry.validated_simulator(self.sim, 64, True)

    def test_reuse_needs_no_compiler_or_auxiliary_rtl(self):
        for option, observed in (('--sim', False), ('--reference-sim', False),
                                 ('--sim', True), ('--reference-sim', True)):
            with self.subTest(option=option, observed=observed):
                observer_name = str(entry.OBSERVER.relative_to(entry.ROOT))
                if observed:
                    self.manifest['source_sha256'][observer_name] = entry.digest(entry.OBSERVER)
                else:
                    self.manifest['source_sha256'].pop(observer_name, None)
                self.write_manifest()
                out = self.root/(option.removeprefix('--') + str(observed))
                arguments = ['run_npu.py', '--out', str(out), option, str(self.sim)]
                cases = lambda root, size, **keywords: root/keywords['name']
                result = {'passed': True, 'measurements': [{'int32_checks': 1}]*21}
                with patch('sys.argv', arguments), \
                     patch.object(entry.shutil, 'which', side_effect=AssertionError('compiler requested')), \
                     patch.object(entry, 'build_simulator', side_effect=AssertionError('build requested')), \
                     patch.object(entry.npu, 'precision_task', side_effect=cases), \
                     patch.object(entry, 'configure', side_effect=lambda path, **keywords: path), \
                     patch.object(entry.npu, 'run_suite', return_value=result), \
                     contextlib.redirect_stdout(io.StringIO()):
                    entry.main()
                summary = json.loads((out/'summary.json').read_text())
                self.assertTrue(summary['passed'])
                self.assertEqual(summary['cases'], 21)
                self.assertEqual(summary['embedded_capacity_assertions'], observed)
                self.assertEqual(list(out.glob('*.sv')), [])

    def test_build_tracks_external_observer(self):
        source = entry.ROOT/entry.CAPACITY_SOURCES[0]
        source_files = lambda root: ([source], [], [source])

        def build(*arguments, **keywords):
            files, _, tracked = entry.npu.source_files(entry.ROOT)
            self.assertEqual(files, [source, entry.OBSERVER])
            self.assertEqual(tracked, files)
            self.manifest['source_sha256'][str(entry.OBSERVER.relative_to(entry.ROOT))] = entry.digest(entry.OBSERVER)
            self.write_manifest()
            return self.binary

        with patch.object(entry.shutil, 'which', return_value='/compiler/verilator'), \
             patch.object(entry.npu, 'source_files', source_files), \
             patch.object(entry.npu, 'build', side_effect=build):
            binary, manifest = entry.build_simulator(self.sim, 'verilator', 1, 64)
            self.assertIs(entry.npu.source_files, source_files)
        self.assertEqual(binary, self.binary)
        self.assertEqual(manifest['source_sha256'][str(entry.OBSERVER.relative_to(entry.ROOT))],
                         entry.digest(entry.OBSERVER))

    def test_build_restores_source_reader_after_exception(self):
        source_files = entry.npu.source_files
        with patch.object(entry.shutil, 'which', return_value='/compiler/verilator'), \
             patch.object(entry.npu, 'build', side_effect=RuntimeError('build stopped')):
            with self.assertRaisesRegex(RuntimeError, 'build stopped'):
                entry.build_simulator(self.sim, 'verilator', 1, 64)
        self.assertIs(entry.npu.source_files, source_files)


if __name__ == '__main__':
    unittest.main()
