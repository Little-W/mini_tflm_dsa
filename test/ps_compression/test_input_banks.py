"""检查共享输入存储块选择与实际格式、紧凑参数之间的关系。"""
import unittest

from run_shared_npu import input_bank_count


class InputBankCountTest(unittest.TestCase):
    def test_noncompact_inputs_need_two_blocks(self):
        for mode in (0, 1):
            for wide in (False, True):
                with self.subTest(mode=mode, wide=wide):
                    self.assertEqual(input_bank_count(
                        {'ia_compact_enable': 0}, mode=mode, lhs_s16=wide), 2)

    def test_compact_selection_uses_the_stream_operand(self):
        for mode, wide, expected in ((0, False, 1), (0, True, 2),
                                     (1, False, 1), (1, True, 1)):
            with self.subTest(mode=mode, wide=wide):
                self.assertEqual(input_bank_count(
                    {'ia_compact_enable': 1}, mode=mode, lhs_s16=wide), expected)

    def test_requested_storage_is_preserved(self):
        for compact in (0, 1):
            for mode in (0, 1):
                self.assertEqual(input_bank_count(
                    {'ia_compact_enable': compact}, mode=mode, lhs_s16=False,
                    requested_banks=2), 2)

    def test_parameter_must_be_recorded(self):
        for manifest in ({}, {'ia_compact_enable': 2}):
            with self.subTest(manifest=manifest):
                with self.assertRaisesRegex(RuntimeError, 'IA_COMPACT_ENABLE'):
                    input_bank_count(manifest, mode=0, lhs_s16=False)


if __name__ == '__main__':
    unittest.main()
