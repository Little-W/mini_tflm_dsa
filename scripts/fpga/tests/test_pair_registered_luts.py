#!/usr/bin/env python3
"""检查寄存 LUT 共享的控制兼容性、专用输出与原有相对位置。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pair_registered_luts import candidates, compatible_pairs, constrain_pairs
from pair_packed_luts import functional_digest
from test_pair_packed_luts import lut


def group(name, inputs, output, *, clock=90, enable=91, reset=92, kind='FDRE'):
    ff_name = name + '_ff'
    logic = lut(inputs, output, CONSTR_CHILDREN=ff_name)
    ports = {'D': [output], 'Q': [output + 100], 'CK': [clock], 'CE': [enable], 'SR': [reset]}
    ff = {'type': 'SLICE_FFX', 'parameters': {'INIT': '0'},
          'attributes': {'X_ORIG_TYPE': kind, 'CONSTR_PARENT': name,
                         'CONSTR_X': '0', 'CONSTR_Y': '0', 'CONSTR_Z': '10', 'CONSTR_ABS_Z': '0'},
          'connections': ports, 'port_directions': {port: 'output' if port == 'Q' else 'input' for port in ports}}
    if kind in ('FDRE', 'FDSE'):
        ff['attributes']['X_FFSYNC'] = '1'
    return {name: logic, ff_name: ff}


def module(**options):
    return {'cells': {**group('a', [1, 2, 3], 10), **group('b', [3, 4, 5], 11, **options)}}


class RegisteredPairTest(unittest.TestCase):
    def test_pair_preserves_functions_and_register_distance(self):
        m = module()
        before = functional_digest(m)
        selected, _ = candidates(m)
        pairs = compatible_pairs(selected)
        self.assertEqual(pairs, [('a', 'b')])
        constrain_pairs(m, selected, pairs)
        self.assertEqual(before, functional_digest(m))
        self.assertEqual(m['cells']['a']['attributes']['CONSTR_CHILDREN'], 'a_ff;b;b_ff')
        self.assertEqual(int(m['cells']['a_ff']['attributes']['CONSTR_Z'], 2), 2)
        self.assertEqual(int(m['cells']['b']['attributes']['CONSTR_Z'], 2), 1)
        self.assertEqual(int(m['cells']['b_ff']['attributes']['CONSTR_Z'], 2), 3)
        self.assertNotIn('CONSTR_CHILDREN', m['cells']['b']['attributes'])

    def test_control_mismatch(self):
        for options in ({'clock': 93}, {'enable': 93}, {'reset': 93}, {'kind': 'FDCE'}):
            with self.subTest(options=options):
                self.assertEqual(compatible_pairs(candidates(module(**options))[0]), [])
        m = module()
        m['cells']['b_ff']['parameters']['IS_CLK_INVERTED'] = '1'
        self.assertEqual(compatible_pairs(candidates(m)[0]), [])

    def test_external_lut_consumer_is_excluded(self):
        for kind in ('SLICE_LUTX', 'SLICE_FFX', 'CARRY4', 'OBUF'):
            m = module()
            m['cells']['sink'] = {'type': kind, 'connections': {'I': [11]}, 'port_directions': {'I': 'input'}}
            self.assertNotIn('b', candidates(m)[0])
        m = module()
        m['ports'] = {'out': {'direction': 'output', 'bits': [11]}}
        self.assertNotIn('b', candidates(m)[0])

    def test_fixed_latch_and_existing_groups_are_excluded(self):
        for cell, values in [('b', {'CONSTR_PARENT': 'parent'}), ('b', {'CONSTR_CHILDREN': 'b_ff;other'}),
                             ('b', {'BEL': 'fixed'}), ('b', {'X_LUT_AS_DRAM': '1'}),
                             ('b_ff', {'X_FF_AS_LATCH': '1'}), ('b_ff', {'CONSTR_Z': '11'}),
                             ('b_ff', {'CONSTR_ABS_Z': '1'}), ('b_ff', {'REGION': 'fixed'})]:
            with self.subTest(cell=cell, values=values):
                m = module()
                m['cells'][cell]['attributes'].update(values)
                self.assertNotIn('b', candidates(m)[0])

    def test_input_union_and_variable_overlap(self):
        for second in ([4, 5, 6], ['0', 4, 5]):
            m = {'cells': {**group('a', ['0', 2, 3], 10), **group('b', second, 11)}}
            self.assertEqual(compatible_pairs(candidates(m)[0]), [])

    def test_constraint_change_and_duplicate_are_rejected(self):
        m = module()
        selected, _ = candidates(m)
        changed = copy.deepcopy(m)
        changed['cells']['b_ff']['attributes']['CONSTR_Z'] = '11'
        with self.assertRaises(ValueError):
            constrain_pairs(changed, selected, [('a', 'b')])
        with self.assertRaises(ValueError):
            constrain_pairs(m, selected, [('a', 'b'), ('a', 'b')])

    def test_limits_and_unused_groups(self):
        m = module()
        m['cells'].update(group('c', [3, 4, 5], 12))
        selected, _ = candidates(m)
        self.assertEqual(len(compatible_pairs(selected)), 1)
        self.assertEqual(compatible_pairs(selected, 0), [])
        self.assertEqual(len(compatible_pairs(selected, 1)), 1)


if __name__ == '__main__':
    unittest.main()
