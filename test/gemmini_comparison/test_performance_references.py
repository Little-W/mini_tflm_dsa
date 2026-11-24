#!/usr/bin/env python3
"""检查历史源码归属、同容量比较和 buffer-ram 容量范围。"""
import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from check_repository_operators import RESOURCE_PROFILE_KEYS, require_same_resources, verify_reference_sources
from write_final_performance_report import check_capacity, digest, read


class HistoricalReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.directory = self.base / 'results'
        self.directory.mkdir()
        names = ('rtl/npu/top/npu_top.sv', 'rtl/npu/conv/conv_im2col_frontend.sv',
                 'test/gemmini_comparison/run_storage_operators.py')
        source_hashes = {}
        for number, name in enumerate(names):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('source input %d\n' % number)
            source_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'Reference inputs'], check=True)
        commit = subprocess.check_output(['git', '-C', str(self.root), 'rev-parse', 'HEAD'], text=True).strip()
        self.reference = {'remote_commit': commit}
        support = self.base / 'tools/test/gemmini_comparison/run_storage_operators.py'
        support.parent.mkdir(parents=True)
        support.write_text('verification tool\n')
        support_hashes = {str(support): hashlib.sha256(support.read_bytes()).hexdigest()}
        recorded = {str(self.root / name): checksum for name, checksum in source_hashes.items()}
        recorded.update(support_hashes)
        self.manifest = {'returncode': 0, 'sources_unchanged_during_build': True, 'profile': {},
                         'source_sha256': recorded, 'binary_sha256': 'simulator',
                         'command': ['verilator', '--assert', '-DSYNTHESIS=1', '-DXILINX_FPGA=1',
                                     '-DTB_CONV_LOW_LATENCY=1']}
        self.verification = {'passed': True, 'sources_unchanged': True, 'source_revision': commit,
                             'mode': 'low-latency', 'source_root': str(self.root),
                             'compiled_and_planner_repository_sources': source_hashes,
                             'production_rtl_sha256': {name: checksum for name, checksum in source_hashes.items()
                                                       if name.startswith('rtl/')},
                             'verification_support_sha256': support_hashes, 'binary_sha256': 'simulator'}
        self.write('summary.json', {'passed': True, 'source_commit': commit, 'profile': {}})
        self.write('sim/build.json', self.manifest)
        self.write('planner/build.json', self.manifest)
        self.write('historical_source_verification.json', self.verification)

    def write(self, name, value):
        path = self.directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def test_external_tool_with_same_relative_name_has_separate_hash(self):
        result = verify_reference_sources(self.directory, self.reference, 'fast')
        self.assertEqual(result['production_rtl_files'], 2)
        self.assertEqual(result['repository_source_files'], 3)

    def test_modified_rtl_is_rejected(self):
        (self.root / 'rtl/npu/top/npu_top.sv').write_text('changed source\n')
        with self.assertRaisesRegex(ValueError, 'checkout changed'):
            verify_reference_sources(self.directory, self.reference, 'fast')

    def test_omitted_rtl_from_verification_is_rejected(self):
        self.verification['production_rtl_sha256'].pop('rtl/npu/top/npu_top.sv')
        self.write('historical_source_verification.json', self.verification)
        with self.assertRaisesRegex(ValueError, 'RTL input list differs'):
            verify_reference_sources(self.directory, self.reference, 'fast')

    def test_compiled_mode_must_match_selected_reference(self):
        self.manifest['command'][-1] = '-DTB_CONV_LOW_LATENCY=0'
        self.write('sim/build.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'compilation options differ'):
            verify_reference_sources(self.directory, self.reference, 'fast')

    def test_different_cache_capacity_is_rejected(self):
        current = {name: 1 for name in RESOURCE_PROFILE_KEYS}
        previous = dict(current, im2col_cache_bytes=65536)
        with self.assertRaisesRegex(ValueError, 'im2col_cache_bytes'):
            require_same_resources(current, previous)


class CapacityScopeTests(unittest.TestCase):
    def setUp(self):
        profile_names = ('size', 'vector_pe_count', 'bus_width', 'ia_cache_blocks', 'ps_frame_count',
                         'ps_pool_bytes', 'raw_only', 'im2col_cache_bytes', 'shared_bank_bytes', 'shared_bank_count')
        configuration_names = ('SIZE', 'VECTOR_PE_COUNT', 'NPU_AXI_DATA_WIDTH', 'IA_CACHE_BLOCKS',
                               'PS_FRAME_COUNT', 'PS_POOL_BYTES', 'PS_FORCE_RAW', 'IM2COL_CACHE_BYTES',
                               'SHARED_BANK_BYTES', 'SHARED_BANK_COUNT')
        self.profile = {name: 1 for name in profile_names}
        configuration = {name: 1 for name in configuration_names}
        configuration['CAPACITY_BUDGET_BYTES'] = 1024
        row = {'passed': True, 'capabilities_match': True, 'array_bits': 648,
               'data_bits': 600, 'metadata_bits': 40, 'read_only_bits': 8,
               'arrays': {'data': 600, 'metadata': 40, 'rom': 8},
               'other_register_bits': 10000, 'total_bits': 10648,
               'array_bytes': 81, 'total_bytes': 1331, 'budget_remaining_bytes': 943}
        self.snapshot = {'source_commit': 'performance', 'sha256': {'rtl/model.sv': 'source'}}
        self.capacity = {'budget_scope': 'buffer-ram', 'budget_bytes': 1024,
                         'source_unchanged': True, 'performance_source_commit': 'performance',
                         'performance_sources_match': True, 'source_sha256': {'rtl/model.sv': 'source'},
                         'configuration': configuration, 'targets': {'generic': row, 'asic': copy.deepcopy(row)}}

    def test_scalar_registers_are_reported_outside_array_budget(self):
        targets = check_capacity(self.capacity, self.profile, self.snapshot)
        self.assertGreater(targets['generic']['total_bytes'], self.capacity['budget_bytes'])
        self.assertLess(targets['generic']['array_bytes'], self.capacity['budget_bytes'])

    def test_array_over_budget_is_rejected(self):
        self.capacity['budget_bytes'] = 80
        self.capacity['configuration']['CAPACITY_BUDGET_BYTES'] = 80
        for row in self.capacity['targets'].values():
            row['budget_remaining_bytes'] = -1
        with self.assertRaises(AssertionError):
            check_capacity(self.capacity, self.profile, self.snapshot)

    def test_capacity_requires_same_source(self):
        self.snapshot['sha256']['rtl/model.sv'] = 'different source'
        with self.assertRaises(AssertionError):
            check_capacity(self.capacity, self.profile, self.snapshot)

    def test_capacity_requires_same_configuration(self):
        self.profile['im2col_cache_bytes'] = 65536
        with self.assertRaises(AssertionError):
            check_capacity(self.capacity, self.profile, self.snapshot)

    def test_compressed_source_snapshot_keeps_original_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            data = json.dumps(self.snapshot).encode()
            path.with_name(path.name + '.gz').write_bytes(gzip.compress(data))
            self.assertEqual(read(path), self.snapshot)
            self.assertEqual(digest(path), hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    unittest.main()
