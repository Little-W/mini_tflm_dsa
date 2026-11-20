#!/usr/bin/env python3
"""检查组合与寄存 LUT 共用时的输入限制、专用使用者和约束保留。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pair_mixed_luts import registered_candidates, ordinary_candidates, select_pairs, constrain_pairs
from pair_packed_luts import functional_digest
from test_pair_packed_luts import lut
from test_pair_registered_luts import group


class MixedPairTest(unittest.TestCase):
    def module(self):
        return {'cells': {**group('registered', [1, 2, 3], 10), 'ordinary': lut([3, 4, 5], 11)}}

    def test_pair_preserves_register_and_functions(self):
        m = self.module()
        before, register = functional_digest(m), copy.deepcopy(m['cells']['registered_ff'])
        registered, ordinary = registered_candidates(m)[0], ordinary_candidates(m)[0]
        pairs = select_pairs(registered, ordinary)
        self.assertEqual(pairs, [('registered', 'ordinary')])
        constrain_pairs(m, registered, ordinary, pairs)
        self.assertEqual(before, functional_digest(m))
        self.assertEqual(register, m['cells']['registered_ff'])
        self.assertEqual(m['cells']['registered']['attributes']['CONSTR_CHILDREN'], 'registered_ff;ordinary')
        self.assertEqual(int(m['cells']['ordinary']['attributes']['CONSTR_Z'], 2), 1)

    def test_six_inputs_and_no_shared_variable(self):
        for inputs in ([3, 4, 5, 6], [4, 5, '0']):
            m = self.module()
            m['cells']['ordinary'] = lut(inputs, 11)
            self.assertEqual(select_pairs(registered_candidates(m)[0], ordinary_candidates(m)[0]), [])

    def test_dependency_is_rejected(self):
        m = self.module()
        m['cells']['registered']['connections']['A2'] = [11]
        self.assertEqual(select_pairs(registered_candidates(m)[0], ordinary_candidates(m)[0]), [])

    def test_dedicated_consumer_and_existing_constraint_are_preserved(self):
        for kind in ('SLICE_FFX', 'CARRY4', 'F7MUX'):
            m = self.module()
            m['cells']['sink'] = {'type': kind, 'connections': {'D': [11]}, 'port_directions': {'D': 'input'}}
            self.assertEqual(select_pairs(registered_candidates(m)[0], ordinary_candidates(m)[0]), [])
        m = self.module()
        m['cells']['ordinary']['attributes']['CONSTR_PARENT'] = 'parent'
        self.assertEqual(select_pairs(registered_candidates(m)[0], ordinary_candidates(m)[0]), [])

    def test_limits_and_constraint_change(self):
        m = self.module()
        registered, ordinary = registered_candidates(m)[0], ordinary_candidates(m)[0]
        self.assertEqual(select_pairs(registered, ordinary, 0), [])
        with self.assertRaises(ValueError):
            constrain_pairs(m, registered, ordinary, [('registered', 'ordinary'), ('registered', 'ordinary')])
        m = self.module()
        m['cells']['registered_ff']['attributes']['CONSTR_Z'] = '11'
        with self.assertRaises(ValueError):
            constrain_pairs(m, registered, ordinary, [('registered', 'ordinary')])


if __name__ == '__main__':
    unittest.main()
