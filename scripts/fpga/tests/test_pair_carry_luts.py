#!/usr/bin/env python3
"""检查进位 LUT 共享的输入、输出选择器和相对约束条件。"""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pair_carry_luts import Connections, constrain_pairs, select_pairs
from pair_packed_luts import candidates, functional_digest
from test_pair_packed_luts import lut


def relative(parent, z, absolute=True):
    return {'CONSTR_PARENT': parent, 'CONSTR_X': f'{0:032b}', 'CONSTR_Y': f'{0:032b}',
            'CONSTR_Z': f'{z:032b}', 'CONSTR_ABS_Z': f'{int(absolute):032b}'}


def design():
    return {'cells': {
        'carry': {'type': 'CARRY4', 'attributes': {'CONSTR_Z': f'{15:032b}',
                   'CONSTR_ABS_Z': '1', 'CONSTR_CHILDREN': 'upper;ff', 'X_CARRY_DI0_VIA_X': '1'},
                  'connections': {'S0': [10], 'DI0': [3], 'O0': [30]},
                  'port_directions': {'S0': 'input', 'DI0': 'input', 'O0': 'output'}},
        'upper': lut([1, 2], 10, **relative('carry', 0)),
        'lower': lut([2, 4, 5], 20),
        'ff': {'type': 'SLICE_FFX', 'attributes': relative('carry', 2),
               'connections': {'D': [30], 'Q': [40]}, 'port_directions': {'D': 'input', 'Q': 'output'}},
    }}


class CarryPairingTest(unittest.TestCase):
    def selections(self, module):
        slots, _ = Connections(module).available_carry_slots()
        independent, _ = candidates(module)
        return slots, independent, select_pairs(slots, independent)

    def test_local_ff_and_preserved_nested_constraints(self):
        module = design()
        cells = module['cells']
        cells['carry']['attributes']['CONSTR_CHILDREN'] = 'upper'
        cells['upper']['attributes']['CONSTR_CHILDREN'] = 'ff'
        cells['ff']['attributes'] = relative('upper', 2, False)
        before = functional_digest(module)
        old_carry = copy.deepcopy(cells['carry'])
        old_ff = copy.deepcopy(cells['ff'])
        slots, independent, pairs = self.selections(module)
        self.assertEqual(len(pairs), 1)
        constrain_pairs(module, slots, independent, pairs)
        self.assertEqual(before, functional_digest(module))
        self.assertEqual(old_carry, cells['carry'])
        self.assertEqual(old_ff, cells['ff'])
        self.assertEqual(cells['upper']['attributes']['CONSTR_CHILDREN'], 'ff;lower')
        self.assertEqual(Connections(module).coordinate('lower'), ('carry', 0, 0, 1))

    def test_external_carry_sum_and_ff_control_use(self):
        for cell_type, port in [('SLICE_FFX', 'CE'), ('SLICE_LUTX', 'A1'), ('CARRY4', 'CYINIT')]:
            with self.subTest(cell_type=cell_type, port=port):
                module = design()
                module['cells']['external'] = {'type': cell_type, 'connections': {port: [30]},
                                              'port_directions': {port: 'input'}}
                self.assertEqual(self.selections(module)[0], {})
        module = design()
        module['cells']['ff']['attributes']['CONSTR_Z'] = f'{18:032b}'
        self.assertEqual(self.selections(module)[0], {})

    def test_dedicated_co3_continuation(self):
        module = design()
        carry = module['cells']['carry']
        carry['attributes'].pop('X_CARRY_DI0_VIA_X')
        carry['attributes']['X_CARRY_DI3_VIA_X'] = '1'
        carry['connections'] = {'S3': [10], 'DI3': [3], 'O3': [30], 'CO3': [50]}
        carry['port_directions'] = {'S3': 'input', 'DI3': 'input', 'O3': 'output', 'CO3': 'output'}
        module['cells']['upper']['attributes'].update(relative('carry', 48))
        module['cells']['ff']['attributes'] = relative('carry', 50)
        module['cells']['next'] = {'type': 'CARRY4', 'attributes': relative('carry', 15),
                                  'connections': {'CIN': [50]}, 'port_directions': {'CIN': 'input'}}
        module['cells']['next']['attributes']['CONSTR_Y'] = f'{(1 << 32) - 1:032b}'
        self.assertIn('upper', self.selections(module)[0])
        module['cells']['second_next'] = copy.deepcopy(module['cells']['next'])
        self.assertEqual(self.selections(module)[0], {})

    def test_lower_lut_and_lower_ff_are_reserved(self):
        for kind, z in [('SLICE_LUTX', 1), ('SLICE_FFX', 3)]:
            module = design()
            module['cells']['reserved'] = {'type': kind, 'attributes': relative('carry', z),
                                           'connections': {}, 'port_directions': {}}
            self.assertEqual(self.selections(module)[0], {})

    def test_di_mode_sixth_port_and_memory_exclusions(self):
        module = design()
        module['cells']['carry']['attributes']['X_CARRY_DI0_VIA_X'] = '0'
        self.assertEqual(self.selections(module)[0], {})
        for attrs in ({'X_LUT_AS_DRAM': '1'}, {'X_LUT_AS_SRL': '1'}, {'BEL': 'fixed'}):
            module = design()
            module['cells']['upper']['attributes'].update(attrs)
            self.assertEqual(self.selections(module)[0], {})
        module = design()
        module['cells']['upper']['connections']['A6'] = [1]
        module['cells']['upper']['port_directions']['A6'] = 'input'
        self.assertEqual(self.selections(module)[0], {})

    def test_incompatible_inputs_and_direct_dependency(self):
        for inputs in ([2, 4, 5, 6, 7], [2, 10]):
            module = design()
            module['cells']['lower'] = lut(inputs, 20)
            self.assertEqual(self.selections(module)[2], [])

    def test_guide_requires_empty_lower_and_single_donor_position(self):
        module = design()
        module['cells']['lower'] = lut([3, 4, 5], 20)
        slots, independent, pairs = self.selections(module)
        self.assertEqual(pairs, [])
        guide = {'positions': {'upper': 'SLICE_X10Y20/A6LUT', 'lower': 'SLICE_X11Y22/B6LUT'},
                 'occupied': set(), 'lut_occupancy': {'SLICE_X11Y22/B': 1}}
        self.assertEqual(len(select_pairs(slots, independent, guide, 3)), 1)
        self.assertEqual(select_pairs(slots, independent, guide, 2), [])
        guide['occupied'].add('SLICE_X10Y20/A5LUT')
        self.assertEqual(select_pairs(slots, independent, guide, 3), [])
        guide['occupied'] = {'SLICE_X10Y20/A5FF'}
        self.assertEqual(select_pairs(slots, independent, guide, 3), [])
        guide['occupied'] = set()
        guide['lut_occupancy']['SLICE_X11Y22/B'] = 2
        self.assertEqual(select_pairs(slots, independent, guide, 3), [])

    def test_duplicate_pair_is_rejected(self):
        module = design()
        slots, independent, pairs = self.selections(module)
        with self.assertRaises(ValueError):
            constrain_pairs(module, slots, independent, pairs + pairs)

    def test_empty_existing_children_attribute(self):
        module = design()
        module['cells']['upper']['attributes']['CONSTR_CHILDREN'] = ''
        slots, independent, pairs = self.selections(module)
        constrain_pairs(module, slots, independent, pairs)
        self.assertEqual(module['cells']['upper']['attributes']['CONSTR_CHILDREN'], 'lower')


if __name__ == '__main__':
    unittest.main()
