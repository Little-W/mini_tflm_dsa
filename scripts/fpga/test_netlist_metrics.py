#!/usr/bin/env python3
"""Check netlist analysis against small circuits with explicit hardware paths."""
import unittest

from netlist_metrics import analyze, connected_paths, dsp_alu_low_bit_dependencies, register_path_requirement, resources
from netlist_fanout import analyze_fanout
from open_fpga_synth import logic_depth


def cell(kind, inputs, outputs, parameters=None):
    return {'type': kind, 'connections': {**inputs, **outputs},
            'port_directions': {**{p: 'input' for p in inputs}, **{p: 'output' for p in outputs}},
            'parameters': parameters or {}}


def flop(q, d):
    return cell('FDRE', {'D': [d], 'C': [100], 'CE': ['1'], 'R': ['0']}, {'Q': [q]})


class MetricsTest(unittest.TestCase):
    def measure(self, cells):
        result = analyze({'cells': cells, 'netnames': {}})
        self.assertEqual(result['paths']['combinational_cycle_nodes'], [])
        return result

    def test_connected_register_path(self):
        result = self.measure({'first': flop(1, '0'), 'logic': cell('LUT1', {'I0': [1]}, {'O': [2]}),
                               'last': flop(3, 2)})
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 1)
        self.assertEqual(path['startpoint']['cell'], 'first')
        self.assertEqual(path['endpoint']['cell'], 'last')

    def test_root_filter_preserves_combination_edges_and_endpoints(self):
        module = {'cells': {'first': flop(1, '0'), 'selected': flop(2, '0'),
                           'a': cell('LUT1', {'I0': [1]}, {'O': [3]}),
                           'b': cell('LUT1', {'I0': [3]}, {'O': [4]}),
                           'merge': cell('LUT2', {'I0': [4], 'I1': [2]}, {'O': [5]}),
                           'last': flop(6, 5)}, 'netnames': {}}
        self.assertEqual(connected_paths(module)['longest_register_path_cells'], 3)
        filtered = connected_paths(module, root_filter=lambda name, cell, port: name == 'selected')
        self.assertEqual(filtered['longest_register_path_cells'], 1)
        path = filtered['register_to_register_paths'][0]
        self.assertEqual(path['startpoint']['cell'], 'selected')
        self.assertEqual(path['endpoint']['cell'], 'last')
        self.assertEqual(path['path'][0]['cell'], 'merge')
        self.assertTrue(filtered['graph_complete'])

    def test_nine_cell_requirement(self):
        for length in (8, 9, 10):
            cells = {'first': flop(1, '0')}
            for index in range(length):
                cells[f'logic_{index}'] = cell('LUT1', {'I0': [index + 1]}, {'O': [index + 2]})
            cells['last'] = flop(length + 3, length + 1)
            requirement = self.measure(cells)['register_path_requirement']
            self.assertEqual(requirement['observed_combinational_cells'], length)
            self.assertEqual(requirement['maximum_combinational_cells'], 9)
            self.assertEqual(requirement['met'], length <= 9)

    def test_incomplete_path_requirement(self):
        result = register_path_requirement({'longest_register_path_cells': 0, 'graph_complete': False})
        self.assertIsNone(result['met'])

    def test_primary_input_has_no_register_start(self):
        result = self.measure({'logic': cell('LUT1', {'I0': [1]}, {'O': [2]}), 'last': flop(3, 2)})
        self.assertEqual(result['paths']['register_to_register_paths'], [])

    def test_sink_filter_preserves_combination_edges_and_roots(self):
        module = {'cells': {'first': flop(1, '0'),
                           'a': cell('LUT1', {'I0': [1]}, {'O': [2]}),
                           'selected': flop(3, 2),
                           'b': cell('LUT1', {'I0': [2]}, {'O': [4]}),
                           'c': cell('LUT1', {'I0': [4]}, {'O': [5]}),
                           'last': flop(6, 5)}, 'netnames': {}}
        self.assertEqual(connected_paths(module)['longest_register_path_cells'], 3)
        filtered = connected_paths(
            module, root_filter=lambda name, cell, port: name == 'first',
            sink_filter=lambda name, cell, port: name == 'selected' and port == 'D')
        self.assertEqual(filtered['longest_register_path_cells'], 1)
        self.assertEqual(len(filtered['register_to_register_paths']), 1)
        path = filtered['register_to_register_paths'][0]
        self.assertEqual(path['startpoint']['cell'], 'first')
        self.assertEqual(path['endpoint']['cell'], 'selected')
        self.assertEqual(path['path'][0]['cell'], 'a')
        self.assertTrue(filtered['graph_complete'])

    def test_lut6_2_independent_o5(self):
        inputs = {f'I{i}': [1 if i == 0 else ('0' if i < 5 else 2)] for i in range(6)}
        result = self.measure({'first': flop(1, '0'),
                               'pair': cell('LUT6_2', inputs, {'O5': [2], 'O6': [3]}),
                               'last': flop(4, 3)})
        self.assertEqual(result['paths']['longest_register_path_cells'], 2)

    def test_logic_depth_lut6_2_output_dependencies(self):
        inputs = {f'I{i}': [1 if i == 0 else ('0' if i < 5 else 2)] for i in range(6)}
        cells = {'first': flop(1, '0'),
                 'pair': cell('LUT6_2', inputs, {'O5': [2], 'O6': [3]}),
                 'last': flop(4, 3)}
        self.assertEqual([item['cell'] for item in logic_depth(cells)], ['pair', 'pair'])

    def test_logic_depth_includes_lut6_2(self):
        cells = {'first': cell('LUT1', {'I0': [1]}, {'O': [2]}),
                 'pair': cell('LUT6_2', {'I0': [2], 'I5': ['1']}, {'O5': [3], 'O6': [4]}),
                 'last': cell('LUT2', {'I0': [3], 'I1': [4]}, {'O': [5]})}
        self.assertEqual([item['cell'] for item in logic_depth(cells)], ['first', 'pair', 'last'])

    def test_carry_has_no_reverse_dependency(self):
        result = self.measure({'first': flop(1, '0'),
            'carry': cell('CARRY4', {'CI': [1], 'CYINIT': ['0'], 'S': ['0'] * 4,
                                   'DI': ['0', '0', '0', 2]},
                          {'O': [2, 3, 4, 5], 'CO': [6, 7, 8, 9]}), 'last': flop(10, 9)})
        self.assertEqual(result['paths']['longest_register_path_cells'], 2)

    def test_logic_depth_carry_direction(self):
        cells = {'first': flop(1, '0'),
                 'carry': cell('CARRY4', {'CI': [1], 'CYINIT': ['0'], 'S': ['0'] * 4,
                                        'DI': ['0', '0', '0', 2]},
                               {'O': [2, 3, 4, 5], 'CO': [6, 7, 8, 9]}), 'last': flop(10, 9)}
        self.assertEqual(len(logic_depth(cells)), 2)

    def test_carry_with_only_carry_output(self):
        result = self.measure({'first': flop(1, '0'),
            'carry': cell('CARRY4', {'CI': [1], 'CYINIT': ['0'], 'S': ['0'] * 4,
                                   'DI': ['0'] * 4}, {'CO': [2, 3, 4, 5]}),
            'last': flop(6, 5)})
        self.assertEqual(result['paths']['longest_register_path_cells'], 1)
        self.assertTrue(result['paths']['graph_complete'])

    def test_shift_register_read_address_is_combinational(self):
        result = self.measure({'address': flop(1, '0'), 'data': flop(2, '0'),
            'srl': cell('SRL16E', {'A0': [1], 'A1': ['0'], 'A2': ['0'], 'A3': ['0'],
                                  'D': [2], 'CLK': [100], 'CE': ['1']}, {'Q': [3]}),
            'last': flop(4, 3)})
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 1)
        self.assertEqual(path['startpoint']['cell'], 'address')
        self.assertEqual(path['endpoint']['cell'], 'last')

    def test_unregistered_dsp_remains_in_path(self):
        result = self.measure({'first': flop(1, '0'),
            'dsp': cell('DSP48E1', {'A': [1], 'CLK': [100]}, {'P': [2]}, {'PREG': '0', 'AREG': '0'}),
            'last': flop(3, 2)})
        self.assertEqual(result['paths']['longest_register_path_cells'], 1)
        self.assertEqual(result['paths']['dsp_without_output_register'], ['dsp'])

    def test_registered_dsp_terminates_path(self):
        cells = {'first': flop(1, '0'),
            'dsp': cell('DSP48E1', {'A': [1], 'CLK': [100]}, {'P': [2]}, {'PREG': '1'}),
            'last': flop(3, 2)}
        result = self.measure(cells)
        self.assertEqual(result['paths']['longest_register_path_cells'], 1)
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['path'][0]['output_internal_registers'], ['PREG'])
        self.assertEqual(path['endpoint']['external_input_port'], 'A')
        output_paths = connected_paths({'cells': cells, 'netnames': {}},
                                      root_filter=lambda name, _cell, port: name == 'dsp' and port == 'P')
        self.assertEqual(output_paths['longest_register_path_cells'], 0)

    def test_dsp_internal_register_before_output_arithmetic(self):
        for registers in ({'AREG': 1, 'BREG': 1}, {'MREG': 1},
                          {'ADREG': 1, 'USE_DPORT': 'TRUE'}, {'OPMODEREG': 1}):
            for output in ('P', 'PCOUT'):
                cells = {'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'OPMODE': [3], 'CLK': [100]},
                                    {output: [4]}, {'PREG': 0, **registers}), 'last': flop(5, 4)}
                result = self.measure(cells)
                path = result['paths']['register_to_register_paths'][0]
                self.assertEqual(path['combinational_cells'], 1)
                self.assertEqual(path['path'][0]['cell'], 'dsp')
                self.assertEqual(path['path'][0]['output_port'], output + '[0]')
                self.assertEqual(path['startpoint']['port'], 'INTERNAL_REGISTER_OUTPUT')
                self.assertIn('input_internal_registers', path['path'][0])
                fanout = analyze_fanout({'cells': cells}, result['paths'])
                self.assertEqual(fanout['register_path_groups'][0]['maximum_pin_fanout'], 1)

    def test_dsp_arithmetic_plus_lut_limit(self):
        for length in (8, 9):
            cells = {'dsp': cell('DSP48E1', {'A': [50], 'B': [51], 'CLK': [100]},
                                 {'P': [1]}, {'PREG': 0, 'AREG': 1, 'BREG': 1})}
            for index in range(length):
                cells[f'logic_{index}'] = cell('LUT1', {'I0': [index + 1]}, {'O': [index + 2]})
            cells['last'] = flop(80, length + 1)
            result = self.measure(cells)
            self.assertEqual(result['paths']['longest_register_path_cells'], length + 1)
            self.assertEqual(result['register_path_requirement']['met'], length == 8)

    def test_dsp_combination_between_two_registered_boundaries(self):
        cells = {'first_dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'CLK': [100]},
                                   {'PCOUT': [3]}, {'AREG': 1, 'BREG': 1, 'PREG': 0}),
                 'last_dsp': cell('DSP48E1', {'PCIN': [3], 'CLK': [100]},
                                  {'P': [4]}, {'PREG': 1}), 'last': flop(5, 4)}
        result = self.measure(cells)
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 2)
        self.assertEqual([step['cell'] for step in path['path']], ['first_dsp', 'last_dsp'])
        fanout = analyze_fanout({'cells': cells}, result['paths'])
        self.assertEqual(fanout['register_path_groups'][0]['maximum_pin_fanout'], 1)

    def test_unregistered_input_path_is_not_counted_twice(self):
        cells = {'first': flop(1, '0'), 'logic': cell('LUT1', {'I0': [1]}, {'O': [2]}),
                 'dsp': cell('DSP48E1', {'A': [50], 'C': [2], 'CLK': [100]},
                              {'P': [3]}, {'AREG': 1, 'CREG': 0, 'PREG': 0}), 'last': flop(4, 3)}
        path = self.measure(cells)['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 2)
        self.assertEqual(path['startpoint']['cell'], 'first')
        self.assertEqual([step['cell'] for step in path['path']], ['logic', 'dsp'])

    def test_dsp_direct_cascade_and_multiplier_register_outputs(self):
        for output, parameters in [('ACOUT', {'AREG': 1, 'ACASCREG': 1}),
                                   ('BCOUT', {'BREG': 1, 'BCASCREG': 1}),
                                   ('MULTSIGNOUT', {'MREG': 1})]:
            cells = {'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'C': [3], 'CLK': [100]},
                                 {output: [4]}, {'PREG': 0, **parameters}), 'last': flop(5, 4)}
            self.assertEqual(self.measure(cells)['paths']['longest_register_path_cells'], 0)

    def test_dsp_internal_input_and_output_registers(self):
        result = self.measure({'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'CLK': [100]},
                                          {'P': [3]}, {'AREG': 1, 'BREG': 1, 'PREG': 1})})
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 1)
        self.assertEqual(path['path'][0]['output_internal_registers'], ['PREG'])
        self.assertEqual(path['path'][0]['input_internal_registers'], ['AREG', 'BREG'])

    def test_dsp_cascade_input_uses_data_register(self):
        cells = {'first': flop(1, '0'),
                 'dsp': cell('DSP48E1', {'ACIN': [1], 'CLK': [100]}, {'P': [2], 'ACOUT': [3]},
                             {'A_INPUT': 'CASCADE', 'AREG': 1, 'ACASCREG': 0, 'PREG': 0}),
                 'last': flop(4, 2)}
        paths = connected_paths({'cells': cells}, root_filter=lambda name, _cell, _port: name == 'first',
                                sink_filter=lambda name, _cell, _port: name == 'last')
        self.assertEqual(paths['register_to_register_paths'], [])

    def test_unused_preadder_register_is_not_a_source(self):
        for register in ('ADREG', 'DREG'):
            result = self.measure({'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'D': [5], 'CLK': [100]},
                                               {'P': [3]}, {register: 1, 'USE_DPORT': 'FALSE', 'PREG': 0}),
                                   'last': flop(4, 3)})
            self.assertEqual(result['paths']['register_to_register_paths'], [])

    def test_input_register_to_multiplier_register_has_arithmetic(self):
        result = self.measure({'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'CLK': [100]},
                                           {'MULTSIGNOUT': [3]}, {'AREG': 1, 'MREG': 1, 'PREG': 0}),
                               'last': flop(4, 3)})
        path = result['paths']['register_to_register_paths'][0]
        self.assertEqual(path['combinational_cells'], 1)
        self.assertEqual(path['path'][0]['output_internal_registers'], ['MREG'])

    def test_multiplier_register_preserves_direct_alu_bypass(self):
        for low_mode, expected in [(['1', '1'], 1), (['1', '0'], 0), ([70, 71], 1)]:
            cells = {'first': flop(1, '0'),
                     'dsp': cell('DSP48E1', {'A': [1], 'B': [2], 'OPMODE': low_mode + ['0'] * 5,
                                            'CLK': [100]}, {'P': [3]}, {'MREG': 1, 'PREG': 0}),
                     'last': flop(4, 3)}
            paths = connected_paths({'cells': cells}, root_filter=lambda name, _cell, _port: name == 'first',
                                    sink_filter=lambda name, _cell, _port: name == 'last')
            self.assertEqual(paths['longest_register_path_cells'], expected)

    def test_storage_resources_are_separate(self):
        kinds = ['LUT6'] * 10 + ['LUT6_2'] * 2 + ['RAM32M'] * 3 + ['RAM64X1D'] + ['SRL16E'] * 5
        result = resources({str(i): {'type': kind} for i, kind in enumerate(kinds)})
        self.assertEqual(result['logic_lut_cells'], 12)
        self.assertEqual(result['distributed_ram_lut_sites_nominal'], 14)
        self.assertEqual(result['shift_register_lut_sites_nominal'], 5)
        self.assertEqual(result['lut_sites_nominal_before_packing'], 31)
        self.assertIsNone(result['physical_lut_sites_after_placement'])

    def test_dsp_alu_data_dependency_direction(self):
        settings = {'USE_MULT': 'NONE', 'USE_DPORT': 'FALSE', 'USE_SIMD': 'ONE48',
                    'A_INPUT': 'DIRECT', 'B_INPUT': 'DIRECT', 'OPMODEREG': 0,
                    'INMODEREG': 0, 'CARRYINSELREG': 0, 'PREG': 0, 'AREG': 0, 'BREG': 0, 'CREG': 0}
        control = {'OPMODE': list(reversed('0110011')), 'INMODE': ['0']*5,
                   'CARRYINSEL': ['0']*3, 'ALUMODE': [70, 71, 72, 73], 'CARRYIN': [74]}
        for output in ('P', 'PCOUT'):
            for port, width, offset in [('A', 30, 18), ('B', 18, 0), ('C', 48, 0)]:
                for source_bit, target_bit in [(0, 0), (0, 18), (7, 2), (2, 7), (width-1, 47)]:
                    data = {name: ['0']*bits for name, bits in [('A', 30), ('B', 18), ('C', 48)]}
                    data[port][source_bit] = 1
                    result = ['0']*48
                    result[target_bit] = 2
                    dsp = cell('DSP48E1', {**control, **data}, {output: result}, settings)
                    module = {'cells': {'first': flop(1, '0'), 'dsp': dsp, 'last': flop(3, 2)}}
                    measured = connected_paths(module, root_filter=lambda name, _cell, _port: name == 'first',
                                               sink_filter=lambda name, _cell, _port: name == 'last')
                    self.assertEqual(measured['longest_register_path_cells'],
                                     int(source_bit + offset <= target_bit), (output, port, source_bit, target_bit))

    def test_dsp_alu_unknown_control_keeps_conservative_dependencies(self):
        control = {'C': ['0']*7+[1]+['0']*40, 'OPMODE': list(reversed('0110011')),
                   'INMODE': ['0']*5, 'CARRYINSEL': ['0']*3}
        settings = {'USE_MULT': 'NONE', 'USE_DPORT': 'FALSE', 'USE_SIMD': 'ONE48',
                    'OPMODEREG': 0, 'INMODEREG': 0, 'CARRYINSELREG': 0, 'PREG': 0}
        output = ['0', '0', 2]+['0']*45
        variants = [({'OPMODE': [70]+control['OPMODE'][1:]}, {}),
                    ({'CARRYINSEL': ['1', '0', '0']}, {}), ({}, {'USE_MULT': 'MULTIPLY'}),
                    ({}, {'USE_SIMD': 'TWO24'}), ({}, {'OPMODEREG': 1}),
                    ({}, {'IS_OPMODE_INVERTED': 1}), ({}, {'A_INPUT': 'CASCADE'})]
        for ports, params in variants:
            dsp = cell('DSP48E1', {**control, **ports}, {'P': output}, {**settings, **params})
            self.assertFalse(dsp_alu_low_bit_dependencies(dsp))
            module = {'cells': {'first': flop(1, '0'), 'dsp': dsp, 'last': flop(3, 2)}}
            measured = connected_paths(module, root_filter=lambda name, _cell, _port: name == 'first',
                                       sink_filter=lambda name, _cell, _port: name == 'last')
            self.assertEqual(measured['longest_register_path_cells'], 1)

    def test_four12_arithmetic_keeps_data_within_each_lane(self):
        settings = {'USE_MULT': 'NONE', 'USE_DPORT': 'FALSE', 'USE_SIMD': 'FOUR12',
                    'A_INPUT': 'DIRECT', 'B_INPUT': 'DIRECT', 'OPMODEREG': 0,
                    'INMODEREG': 0, 'CARRYINSELREG': 0, 'PREG': 0, 'AREG': 0, 'BREG': 0, 'CREG': 0}
        control = {'OPMODE': list(reversed('0110011')), 'INMODE': ['0'] * 5,
                   'CARRYINSEL': ['0'] * 3, 'ALUMODE': [70, 71, 72, 73], 'CARRYIN': [74]}
        boundaries = (0, 11, 12, 17, 18, 23, 24, 35, 36, 47)
        for output in ('P', 'PCOUT'):
            for port, width, offset in (('A', 30, 18), ('B', 18, 0), ('C', 48, 0)):
                for source in boundaries:
                    if not offset <= source < offset + width:
                        continue
                    for target in boundaries:
                        data = {name: ['0'] * bits for name, bits in (('A', 30), ('B', 18), ('C', 48))}
                        data[port][source - offset] = 1
                        result = ['0'] * 48
                        result[target] = 2
                        dsp = cell('DSP48E1', {**control, **data}, {output: result}, settings)
                        module = {'cells': {'first': flop(1, '0'), 'dsp': dsp, 'last': flop(3, 2)}}
                        measured = connected_paths(module, root_filter=lambda name, _cell, _port: name == 'first',
                                                   sink_filter=lambda name, _cell, _port: name == 'last')
                        expected = source // 12 == target // 12 and source <= target
                        self.assertEqual(measured['longest_register_path_cells'], int(expected),
                                         (output, port, source, target))


if __name__ == '__main__':
    unittest.main()
