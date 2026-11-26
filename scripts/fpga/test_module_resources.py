#!/usr/bin/env python3
import unittest
from unittest.mock import patch

from module_resources import attribute_resources


def lut(input_bit, output_bit):
    return {'type': 'LUT1', 'connections': {'I0': [input_bit], 'O': [output_bit]},
            'port_directions': {'I0': 'input', 'O': 'output'}, 'attributes': {}}


def ff(input_bit, output_bit, source):
    return {'type': 'FDRE', 'connections': {'D': [input_bit], 'Q': [output_bit]},
            'port_directions': {'D': 'input', 'Q': 'output'}, 'attributes': {'src': source + ':10.1'}}


class ModuleResourcesTests(unittest.TestCase):
    def test_flattened_sources_use_the_functional_module(self):
        dependencies = {'rtl/top.sv': {'rtl/bridge.sv', 'rtl/leaf.sv'},
                        'rtl/bridge.sv': {'rtl/leaf.sv'}, 'rtl/leaf.sv': set()}
        cell = ff(2, 3, 'rtl/top.sv')
        cell['attributes']['src'] = 'rtl/top.sv:20.1|rtl/leaf.sv:8.2|rtl/bridge.sv:12.1'
        module = {'cells': {'logic': lut(1, 2), 'register': cell}, 'ports': {}}
        with patch('module_resources.source_dependencies', return_value=dependencies):
            result = attribute_resources(module, {})
        self.assertEqual(result['module_resources'], [
            {'rtl_source_or_group': 'rtl/leaf.sv', 'logic_lut_cells': 1, 'flip_flops': 1}])

    def test_chain_has_one_destination_owner(self):
        module = {'cells': {'a': lut(1, 2), 'b': lut(2, 3), 'ff': ff(3, 4, 'rtl/a.sv')}, 'ports': {}}
        result = attribute_resources(module, {'ff': 'u_a.value [0]'})
        row = result['module_resources'][0]
        self.assertEqual(row['rtl_source_or_group'], 'rtl/a.sv')
        self.assertEqual(row['logic_lut_cells'], 2)

    def test_fanout_is_reported_as_shared(self):
        module = {'cells': {'a': lut(1, 2), 'fa': ff(2, 3, 'rtl/a.sv'),
                            'fb': ff(2, 4, 'rtl/b.sv')}, 'ports': {}}
        result = attribute_resources(module, {})
        row = result['module_resources'][0]
        self.assertEqual(row['rtl_source_or_group'], 'shared_between_modules')
        self.assertEqual(row['logic_lut_cells'], 1)
        self.assertEqual(result['mixed_lut_groups'][0]['consumers'], ['rtl/a.sv', 'rtl/b.sv'])

    def test_source_attribute_supplies_direct_owner(self):
        cell = lut(1, 2)
        cell['attributes']['src'] = 'rtl/explicit.sv:20.1'
        result = attribute_resources({'cells': {'lut': cell}, 'ports': {}}, {})
        self.assertEqual(result['module_resources'][0]['rtl_source_or_group'], 'rtl/explicit.sv')


if __name__ == '__main__':
    unittest.main()
