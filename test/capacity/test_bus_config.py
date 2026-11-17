#!/usr/bin/env python3
"""Validate configurable NPU data width and shared-bank storage settings."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from capacity import config, menuconfig, model
from capacity.menuconfig_state import MenuConfigState

SOLVER = ROOT / 'scripts/capacity/solve.py'


def clean_environment():
    values = dict(os.environ)
    for name in (*config.DEFAULTS, 'NPU_CONFIG', 'MAKEFLAGS', 'MFLAGS', 'MAKELEVEL',
                 'GNUMAKEFLAGS', 'NPU_CONFIG_INCLUDED'):
        values.pop(name, None)
    return values


def result_json(text):
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character == '{':
            try:
                return decoder.raw_decode(text[index:])[0]
            except json.JSONDecodeError:
                pass
    raise AssertionError('Expected a JSON result: ' + text)


class BusConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-bus-config-')
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.path = self.directory / 'npu.mk'
        self.file_values = {**config.DEFAULTS, 'NPU_AXI_DATA_WIDTH': 32,
                            'SHARED_BANK_BYTES': 1024, 'SHARED_BANK_COUNT': 6}
        self.path.write_text(''.join(f'{key} ?= {value}\n' for key, value in self.file_values.items()))
        environment = mock.patch.dict(os.environ, clean_environment(), clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def run_cli(self, *arguments, env=None):
        result = subprocess.run([sys.executable, str(SOLVER), *map(str, arguments)],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result_json(result.stdout)

    def test_file_environment_and_explicit_priority(self):
        self.assertEqual(config.axi_data_width(config_path=self.path), 32)
        self.assertEqual(config.selected_config(self.path), self.file_values)
        with mock.patch.dict(os.environ, {'NPU_CONFIG': str(self.path),
                'NPU_AXI_DATA_WIDTH': '64', 'SHARED_BANK_BYTES': '4096', 'SHARED_BANK_COUNT': '9'}):
            selected = config.selected_config()
            self.assertEqual((selected['NPU_AXI_DATA_WIDTH'], selected['SHARED_BANK_BYTES'],
                              selected['SHARED_BANK_COUNT']), (64, 4096, 9))
            self.assertEqual(config.axi_data_width(), 64)
            self.assertEqual(config.axi_data_width(32), 32)
            direct = self.run_cli('--show')
            self.assertEqual(direct['configuration'], selected)
            explicit = self.run_cli('--show', '--config', self.path,
                                    '--set', 'NPU_AXI_DATA_WIDTH=32',
                                    '--set', 'SHARED_BANK_BYTES=2048', '--set', 'SHARED_BANK_COUNT=7')
            self.assertEqual(explicit['configuration']['NPU_AXI_DATA_WIDTH'], 32)
            self.assertEqual(explicit['allocation']['shared_total_bytes'], 14336)

    def test_menu_initialization_overrides_and_reload(self):
        with mock.patch.dict(os.environ, {'NPU_AXI_DATA_WIDTH': '64',
                'SHARED_BANK_BYTES': '2048', 'SHARED_BANK_COUNT': '8'}):
            state = MenuConfigState(self.path, overrides={'NPU_AXI_DATA_WIDTH': 32,
                                   'SHARED_BANK_BYTES': '4 KiB', 'SHARED_BANK_COUNT': 9})
            self.assertEqual((state.values['NPU_AXI_DATA_WIDTH'], state.values['SHARED_BANK_BYTES'],
                              state.values['SHARED_BANK_COUNT']), (32, 4096, 9))
            self.assertTrue(state.dirty)
            state.reload()
            self.assertEqual(state.values, self.file_values)
            self.assertFalse(state.dirty)

    def test_all_supported_geometries_and_equal_raw_capacity(self):
        for width in (32, 64):
            for bank_bytes in (1024, 2048, 4096):
                for bank_count in range(6, 10):
                    values = {**config.DEFAULTS, 'NPU_AXI_DATA_WIDTH': width,
                              'SHARED_BANK_BYTES': bank_bytes, 'SHARED_BANK_COUNT': bank_count}
                    adaptive = config.validate_config(values)
                    raw = config.validate_config({**values, 'PS_FORCE_RAW': 1})
                    a = config.allocation_from_config(adaptive)
                    b = config.allocation_from_config(raw)
                    self.assertEqual(a['shared_total_bytes'], bank_bytes*bank_count)
                    self.assertEqual(a['buffer_arrays_bits'], b['buffer_arrays_bits'])
                    self.assertEqual(a['payload_bank_depth'], bank_bytes//16)
                    self.assertEqual(raw['CAPACITY_REPRESENTATION'], 'raw32')
        keys = {field.key for field in menuconfig.FIELDS}
        self.assertIn('NPU_AXI_DATA_WIDTH', keys)
        self.assertIn('SHARED_BANK_BYTES', keys)
        self.assertIn('SHARED_BANK_COUNT', keys)
        self.assertNotIn('SHARED_IA_PS_ENABLE', keys | set(config.DEFAULTS))

    def test_invalid_settings_are_rejected(self):
        for key, invalid in (('NPU_AXI_DATA_WIDTH', (0, 16, 128, True, 32.0)),
                             ('SHARED_BANK_BYTES', (0, 512, 1536, 8192, True)),
                             ('SHARED_BANK_COUNT', (0, 5, 10, True, 7.0))):
            for value in invalid:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    config.validate_config({**config.DEFAULTS, key: value})
        for key in ('NPU_AXI_DATA_WIDTH', 'SHARED_BANK_BYTES', 'SHARED_BANK_COUNT'):
            with mock.patch.dict(os.environ, {key: '$(echo 64)'}), self.assertRaises(ValueError):
                config.selected_config(self.path)

    def test_generated_header_sets_the_schedule_default(self):
        compiler = shutil.which('gcc')
        if compiler is None:
            self.skipTest('A C compiler is required')
        for width in (32, 64):
            header = self.directory / f'config_{width}.h'
            result = self.run_cli('--config', self.path, '--emit-c-header', header,
                                  '--set', f'NPU_AXI_DATA_WIDTH={width}',
                                  '--set', 'SHARED_BANK_BYTES=4096', '--set', 'SHARED_BANK_COUNT=9')
            self.assertEqual(result['allocation']['shared_total_bytes'], 36864)
            text = header.read_text()
            self.assertIn(f'#define NPU_CONFIG_NPU_AXI_DATA_WIDTH {width}', text)
            self.assertIn('#define NPU_CONFIG_SHARED_BANK_BYTES 4096', text)
            self.assertIn('#define NPU_CONFIG_SHARED_BANK_COUNT 9', text)
            source = self.directory / f'check_{width}.c'
            source.write_text('#include "' + str(header) + '"\n#include "dsa_schedule.h"\n'
                              'int main(void){dsa_schedule_config_t c;'
                              'dsa_schedule_init(&c,1,16,16,16,4,16);'
                              f'return c.axi_data_bits!={width}u || c.dma_max_bytes!={width//8*256}u;}}\n')
            binary = self.directory / f'check_{width}'
            subprocess.run([compiler, '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
                            '-I', str(ROOT / 'drivers'), str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_solver_and_menu_save_selected_bank_geometry(self):
        for bank_bytes in (1024, 2048, 4096):
            state = MenuConfigState(self.path, shapes=[dict(M=512, K=16, N=32)],
                    overrides={'NPU_AXI_DATA_WIDTH': 64, 'SHARED_BANK_BYTES': bank_bytes})
            result = state.solve()
            allocation = result['allocation']
            self.assertEqual(allocation['shared_bank_bytes'], bank_bytes)
            state.save()
            saved = config.read_config(self.path)
            self.assertEqual(saved['NPU_AXI_DATA_WIDTH'], 64)
            self.assertEqual(saved['SHARED_BANK_BYTES'], bank_bytes)
            self.assertEqual(saved['SHARED_BANK_COUNT'], allocation['shared_physical_bank_count'])
            actual = config.allocation_from_config(saved)
            self.assertEqual(actual['buffer_ram_bits'], allocation['buffer_ram_bits'])
        result = self.run_cli('--config', self.path, '--shape', '512,16,32',
                              '--set', 'SHARED_BANK_BYTES=1024', '--apply')
        saved = config.read_config(self.path)
        self.assertEqual(saved['SHARED_BANK_BYTES'], 1024)
        self.assertEqual(saved['SHARED_BANK_COUNT'], result['allocation']['shared_physical_bank_count'])
        self.assertEqual(saved['NPU_AXI_DATA_WIDTH'], 64)

    @unittest.skipUnless(shutil.which('make'), 'GNU Make is required')
    def test_make_explicit_settings_override_environment_and_file(self):
        env = {**clean_environment(), 'NPU_AXI_DATA_WIDTH': '64',
               'SHARED_BANK_BYTES': '2048', 'SHARED_BANK_COUNT': '7'}
        run = subprocess.run(['make', '--no-print-directory', 'capacity-show',
                              f'NPU_CONFIG={self.path}', 'NPU_AXI_DATA_WIDTH=32',
                              'SHARED_BANK_BYTES=4096', 'SHARED_BANK_COUNT=9'],
                             cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout+run.stderr)
        result = result_json(run.stdout)
        self.assertEqual(result['configuration']['NPU_AXI_DATA_WIDTH'], 32)
        self.assertEqual(result['allocation']['shared_total_bytes'], 36864)


if __name__ == '__main__':
    unittest.main()
