"""检查 WS 参数寄存容量与 IS 参数存储的独立归属。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.capacity import elaboration, model


class ParameterCapacityTests(unittest.TestCase):
    def test_ws_regfile_is_register_state(self):
        for bank in range(2):
            for instance in ('u_multiplier', 'u_shift'):
                path = f'npu_top.u_requant.g_full.u_full.g_ws_bank_write.g_bank[{bank}].{instance}'
                ancestors = ('npu_top', 'vec_requant', 'vec_requant_full')
                self.assertIsNone(elaboration.array_category('regfile', 'mem', ancestors, path))
                self.assertEqual(elaboration.register_array_category('regfile', 'mem', ancestors, path),
                                 'requant_ws_parameters')

    def test_is_regfile_keeps_independent_capacity(self):
        path = 'npu_top.u_requant.g_full.u_full.gen_is_parameter_bank[0].u_multiplier'
        ancestors = ('npu_top', 'vec_requant', 'vec_requant_full')
        self.assertEqual(elaboration.array_category('regfile', 'mem', ancestors, path), 'requant_is_cache')
        self.assertIsNone(elaboration.register_array_category('regfile', 'mem', ancestors, path))

    def test_direct_parameter_arrays_have_same_category(self):
        for name in ('ch_multiplier_lane_r', 'ch_shift_lane_r', 'ch_product_multiplier_lane_r',
                     'ch_product_amount_lane_r'):
            self.assertEqual(elaboration.register_array_category('vec_requant_full', name),
                             'requant_ws_parameters')

    def test_production_capacity(self):
        geometry = dict(bank_count=7, bank_bytes=8192)
        buffers = model.buffer_arrays_bits(4, 16, 49152, 16, True, **geometry)
        registers = model.register_arrays_bits(4, 16, 49152, 16, True, **geometry)
        self.assertEqual(buffers['requant_is_cache'], 52736)
        self.assertEqual(registers['requant_ws_parameters'], 1648)


if __name__ == '__main__':
    unittest.main()
