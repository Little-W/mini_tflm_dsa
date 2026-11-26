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
            'ia_compact_enable': 0, 'ps_frame_count': 16,
            'ps_storage_rows': 799, 'oa_s16_fifo_banks_max': 4,
            'binary_sha256': entry.digest(self.binary),
            'source_sha256': {name: entry.digest(entry.ROOT/name)
                              for name in entry.CAPACITY_SOURCES},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.sim/'build.json').write_text(json.dumps(self.manifest))

    def test_current_program_and_capacity_sources(self):
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
                specifications = entry.capacity_cases(entry.capacity_profile(self.manifest))
                cases = [out/'cases'/spec['name'] for spec in specifications]
                result = {'passed': True, 'measurements': [{'int32_checks': 1}]*len(cases)}
                with patch('sys.argv', arguments), \
                     patch.object(entry.shutil, 'which', side_effect=AssertionError('compiler requested')), \
                     patch.object(entry, 'build_simulator', side_effect=AssertionError('build requested')), \
                     patch.object(entry, 'generate_cases', return_value=(cases, specifications)), \
                     patch.object(entry.npu, 'run_suite', return_value=result), \
                     contextlib.redirect_stdout(io.StringIO()):
                    entry.main()
                summary = json.loads((out/'summary.json').read_text())
                self.assertTrue(summary['passed'])
                self.assertEqual(summary['cases'], 31)
                self.assertEqual(summary['hardware_profile']['maximum_ia_reuse'], 16)
                self.assertEqual(summary['embedded_capacity_assertions'], observed)
                self.assertEqual(list(out.glob('*.sv')), [])

    def test_production_configuration_and_reuse_limits(self):
        profile = entry.capacity_profile(self.manifest)
        self.assertEqual(profile['ia_block_bytes'], 512)
        self.assertEqual(profile['ia_blocks_per_bank'], 16)
        self.assertEqual(profile['maximum_ia_reuse'], 16)
        self.assertEqual(profile['matrix_requant_compute_lanes'], 2)
        self.assertEqual(profile['ps_storage_rows'], 799)
        cases = {case['name']: case for case in entry.capacity_cases(profile)}
        self.assertEqual((cases['ws_capacity_0']['banks'], cases['ws_capacity_0']['r']), (2, 16))
        self.assertEqual(cases['ws_capacity_1']['r'], 16)
        for flow in ('ws', 'is'):
            self.assertEqual(cases[flow + '_r_minimum']['r'], 1)
            self.assertEqual(cases[flow + '_r_minimum']['expected_error'], 0)
            self.assertEqual(cases[flow + '_r_maximum']['r'], 16)
            self.assertEqual(cases[flow + '_r_maximum']['expected_error'], 0)
            self.assertEqual(cases[flow + '_r_zero']['r'], 0)
            self.assertEqual(cases[flow + '_r_zero']['expected_error'], 2)
            self.assertEqual(cases[flow + '_r_above_capacity']['r'], 32)
            self.assertEqual(cases[flow + '_r_above_capacity']['expected_error'], 2)
            self.assertEqual(cases[flow + '_single_noncompact_bank']['r'], 8)
            self.assertEqual(cases[flow + '_single_noncompact_bank']['expected_error'], 1)

    def test_compact_input_and_full_width_ws_input(self):
        profile = entry.capacity_profile({**self.manifest, 'ia_compact_enable': 1})
        self.assertEqual(profile['maximum_ia_reuse'], 32)
        cases = {case['name']: case for case in entry.capacity_cases(profile)}
        self.assertEqual(len(cases), 29)
        self.assertEqual((cases['ws_capacity_0']['banks'], cases['ws_capacity_0']['r']), (1, 16))
        self.assertEqual(cases['ws_capacity_1']['r'], 32)
        self.assertEqual((cases['ws_s16_capacity']['banks'], cases['ws_s16_capacity']['r']), (2, 16))
        self.assertFalse(cases['ws_s16_capacity']['active_compact'])
        self.assertEqual((cases['is_s16_capacity']['banks'], cases['is_s16_capacity']['r']), (1, 16))
        self.assertTrue(cases['is_s16_capacity']['active_compact'])

    def test_original_dimensions_and_invalid_categories(self):
        expected_shapes = [(21, 35, 35), (515, 83, 35), (37, 259, 35),
                           (133, 51, 35), (129, 19, 35), (517, 35, 16)]
        for compact in (0, 1):
            profile = entry.capacity_profile({**self.manifest, 'ia_compact_enable': compact})
            cases = entry.capacity_cases(profile)
            for mode in (0, 1):
                selected = cases[mode*6:(mode+1)*6]
                self.assertEqual([(c['stream_rows'], c['stream_columns'], c['reduction'])
                                  for c in selected], expected_shapes)
                self.assertEqual([c['control'] for c in selected], [0, 0, 14, 10, 6, 1])
                self.assertTrue(all(c['expected_error'] == 0 for c in selected))
            self.assertEqual([(c['stream_rows'], c['stream_columns'], c['wide'])
                              for c in cases[12:14]], [(261, 35, True), (73, 51, True)])
            self.assertEqual([c['name'] for c in cases[14:21]], [
                'invalid_ia_three', 'invalid_ia_four', 'invalid_ia_range',
                'invalid_r_three', 'invalid_r_range', 'invalid_w_range', 'invalid_control_range'])
            self.assertEqual([c['expected_error'] for c in cases[14:21]], [1, 1, 1, 2, 2, 1, 1])

    def test_capacity_parameters_must_be_recorded(self):
        for name in ('ia_compact_enable', 'ps_frame_count', 'ps_storage_rows', 'oa_s16_fifo_banks_max'):
            with self.subTest(parameter=name):
                manifest = dict(self.manifest)
                del manifest[name]
                with self.assertRaisesRegex(RuntimeError, name):
                    entry.capacity_profile(manifest)

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
