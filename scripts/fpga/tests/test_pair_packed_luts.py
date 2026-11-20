#!/usr/bin/env python3
"""检查普通 LUT 配对的输入、依赖、专用资源与约束保留条件。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pair_packed_luts import candidates, constrain_pairs, functional_digest, select_pairs


def lut(inputs, output, **attributes):
    ports = {**{f'A{i + 1}': [bit] for i, bit in enumerate(inputs)}, 'O6': [output]}
    return {'type': 'SLICE_LUTX', 'parameters': {'INIT': '01101001'},
            'attributes': {'X_LUT_LOGICAL_OUTPUT': '1', **attributes}, 'connections': ports,
            'port_directions': {port: 'output' if port == 'O6' else 'input' for port in ports}}


class PairingTest(unittest.TestCase):
    def test_compatible_pair_and_relative_position(self):
        module = {'cells': {'a': lut([1, 2, 3], 10), 'b': lut([3, 4, 5], 11)}}
        before = functional_digest(module)
        selected, _ = candidates(module)
        pairs = select_pairs(selected)
        self.assertEqual(len(pairs), 1)
        constrain_pairs(module, selected, pairs)
        self.assertEqual(before, functional_digest(module))
        upper, lower = (module['cells'][name]['attributes'] for name in pairs[0])
        self.assertNotIn('CONSTR_ABS_Z', upper)
        self.assertNotIn('CONSTR_Z', upper)
        self.assertEqual(int(lower['CONSTR_Z'], 2), 1)
        self.assertEqual(int(lower['CONSTR_ABS_Z'], 2), 0)

    def test_repeated_ports_do_not_hide_six_inputs(self):
        module = {'cells': {'a': lut([1, 1, 1, 2, 3], 10), 'b': lut([1, 1, 4, 5, 6], 11)}}
        selected, _ = candidates(module)
        self.assertEqual(select_pairs(selected), [])

    def test_direct_dependency(self):
        module = {'cells': {'a': lut([1, 2], 10), 'b': lut([1, 10], 11)}}
        selected, _ = candidates(module)
        self.assertEqual(select_pairs(selected), [])

    def test_constant_is_not_shared_variable_input(self):
        module = {'cells': {'a': lut(['0', 2], 10), 'b': lut(['0', 3], 11)}}
        selected, _ = candidates(module)
        self.assertEqual(select_pairs(selected), [])

    def test_existing_constraints_and_storage(self):
        for attributes in ({'CONSTR_PARENT': 'parent'}, {'BEL': 'fixed'}, {'NEXTPNR_BEL': 'placed'},
                           {'REGION': 'area'}, {'DONT_TOUCH': '0'}, {'X_LUT_AS_DRAM': '1 '},
                           {'X_LUT_AS_SRL': '0001'}, {'X_LUT_LOGICAL_OUTPUT': '0'}):
            with self.subTest(attributes=attributes):
                module = {'cells': {'a': lut([1, 2], 10, **attributes), 'b': lut([1, 3], 11)}}
                self.assertNotIn('a', candidates(module)[0])

    def test_sixth_port_and_dedicated_sinks(self):
        module = {'cells': {'a': lut([1, 1, 1, 1, 1, 1], 10)}}
        self.assertNotIn('a', candidates(module)[0])
        for kind in ('CARRY4', 'SLICE_FFX', 'F7MUX', 'F8MUX', 'SELMUX2_1'):
            with self.subTest(kind=kind):
                module = {'cells': {'a': lut([1, 2], 10),
                                   'sink': {'type': kind, 'connections': {'D': [10]},
                                            'port_directions': {'D': 'input'}}}}
                self.assertNotIn('a', candidates(module)[0])

    def test_unique_members_and_limit(self):
        module = {'cells': {str(i): lut([1, 2], 100 + i) for i in range(7)}}
        selected, _ = candidates(module)
        pairs = select_pairs(selected)
        self.assertEqual(len(pairs), 3)
        self.assertEqual(len({name for pair in pairs for name in pair}), 6)
        self.assertEqual(len(select_pairs(selected, 1)), 1)
        self.assertEqual(select_pairs(selected, 0), [])
        invalid = copy.deepcopy(module)
        with self.assertRaises(ValueError):
            constrain_pairs(invalid, selected, [pairs[0], pairs[0]])


if __name__ == '__main__':
    unittest.main()
