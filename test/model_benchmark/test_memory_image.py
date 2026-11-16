#!/usr/bin/env python3
"""Check sparse firmware overlays and little-endian AXI64 memory images."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name('build_sim.py')
SPEC = importlib.util.spec_from_file_location('memory_image_build_sim', MODULE_PATH)
BUILD_SIM = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD_SIM)


class MemoryImageTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def pack(self, firmware, data=None, *, ram_words=524288, data_base_word=0):
        firmware_path = self.root / 'firmware.mem'
        firmware_path.write_text(firmware)
        data_path = None
        if data is not None:
            data_path = self.root / 'data.mem'
            data_path.write_text(data)
        output = self.root / 'memory_axi64.mem'
        BUILD_SIM.pack_memory_images(firmware_path, data_path, output,
                                     ram_words=ram_words, data_base_word=data_base_word)
        return output.read_text()

    def test_adjacent_words_preserve_little_endian_bytes(self):
        packed = self.pack('03020100 07060504 0b0a0908 0f0e0d0c\n')
        self.assertEqual(packed, '@00000000\n0706050403020100\n0f0e0d0c0b0a0908\n')
        payload = b''.join(int(row, 16).to_bytes(8, 'little')
                           for row in packed.splitlines() if not row.startswith('@'))
        self.assertEqual(payload, bytes(range(16)))

    def test_sparse_odd_words_select_upper_lanes(self):
        self.assertEqual(self.pack('@1\n11223344\n@9\naabbccdd\n'),
                         '@00000000\n1122334400000000\n'
                         '@00000004\naabbccdd00000000\n')

    def test_overlay_preserves_other_half_of_each_ram_row(self):
        self.assertEqual(self.pack('11111111 22222222 33333333 44444444\n',
                                   '@1\naaaaaaaa bbbbbbbb\n'),
                         '@00000000\naaaaaaaa11111111\n44444444bbbbbbbb\n')

    def test_explicit_zero_overwrites_existing_word(self):
        self.assertEqual(self.pack('ffffffff 12345678 abcdef01 ffffffff\n',
                                   '@0\n0\n@3\n0\n'),
                         '@00000000\n1234567800000000\n00000000abcdef01\n')

    def test_data_base_and_absolute_address_directives(self):
        self.assertEqual(self.pack('@4\n44444444\n',
                                   '55555555 66666666\n@9\n99999999\n',
                                   data_base_word=5),
                         '@00000002\n5555555544444444\n0000000066666666\n'
                         '9999999900000000\n')

    def test_last_write_to_sparse_address_takes_precedence(self):
        self.assertEqual(self.pack('@1\n11111111\n@1\n22222222\n',
                                   '@1\n33333333\n@1\n44444444\n'),
                         '@00000000\n4444444400000000\n')

    def test_comments_and_digit_separators(self):
        self.assertEqual(self.pack('/* firmware\n header */ @0\n'
                                   '1234_abcd // lower word\n'
                                   '/* upper */ 89AB_CDEF\n'),
                         '@00000000\n89abcdef1234abcd\n')

    def test_final_two_words_of_two_mib_ram(self):
        self.assertEqual(self.pack('@7fffe\n76543210 fedcba98\n'),
                         '@0003ffff\nfedcba9876543210\n')

    def test_final_word_overlay_preserves_adjacent_firmware(self):
        self.assertEqual(self.pack('@7fffe\n11223344 ffffffff\n',
                                   '@7ffff\n0\n'),
                         '@0003ffff\n0000000011223344\n')

    def test_first_word_beyond_ram_is_rejected(self):
        for firmware, data in (('@80000\n1\n', None),
                               ('@7ffff\n1 2\n', None),
                               ('0\n', '@80000\n1\n')):
            with self.subTest(firmware=firmware, data=data):
                with self.assertRaisesRegex(ValueError, 'Invalid 32-bit memory word'):
                    self.pack(firmware, data)

    def test_data_base_cannot_write_beyond_ram(self):
        with self.assertRaisesRegex(ValueError, 'Invalid 32-bit memory word'):
            self.pack('0\n', '12345678\n', data_base_word=524288)

    def test_negative_addresses_are_rejected(self):
        for firmware, data, base in (('@-1\n1\n', None, 0),
                                      ('0\n', '1\n', -1)):
            with self.subTest(firmware=firmware, data=data, base=base):
                with self.assertRaisesRegex(ValueError, 'Invalid 32-bit memory word'):
                    self.pack(firmware, data, data_base_word=base)

    def test_words_outside_unsigned_32_bit_range_are_rejected(self):
        for value in ('100000000', '-1', 'ffff_ffff_ffff_ffff'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'Invalid 32-bit memory word'):
                    self.pack(value + '\n')

    def test_absent_and_empty_data_images_are_equivalent(self):
        expected = '@00000000\n00000000abcdef01\n'
        self.assertEqual(self.pack('abcdef01\n'), expected)
        self.assertEqual(self.pack('abcdef01\n', ''), expected)
        self.assertEqual(self.pack('', None), '')

    def test_output_addresses_are_sorted_without_filling_sparse_gaps(self):
        self.assertEqual(self.pack('@20\naaaaaaaa\n@1\nbbbbbbbb\n@10\ncccccccc\n'),
                         '@00000000\nbbbbbbbb00000000\n'
                         '@00000008\n00000000cccccccc\n'
                         '@00000010\n00000000aaaaaaaa\n')


if __name__ == '__main__':
    unittest.main()
