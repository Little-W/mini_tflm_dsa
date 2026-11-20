#!/usr/bin/env python3
"""验证余因子融合的全部输入、输入排列与专用单元排除条件。"""
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fuse_lut_cofactors import CombinationalDependencies, function_key, fuse_module


def lut(inputs, output, table):
    width = len(inputs)
    return {'type': f'LUT{width}', 'hide_name': 0, 'attributes': {},
            'parameters': {'INIT': f'{table:0{1 << width}b}'},
            'port_directions': {'O': 'output'} | {f'I{i}': 'input' for i in range(width)},
            'connections': {'O': [output]} | {f'I{i}': [bit] for i, bit in enumerate(inputs)}}


def example(selected=5, lower_width=5, seed=37):
    rng = random.Random(seed)
    inputs = list(range(10, 16))
    remaining = [bit for i, bit in enumerate(inputs) if i != selected]
    lower_inputs = list(reversed(remaining[:lower_width]))
    lower_table = rng.getrandbits(1 << lower_width)
    upper_table = 0
    for address in range(64):
        values = {bit: (address >> i) & 1 for i, bit in enumerate(inputs)}
        lower_address = sum(values[bit] << i for i, bit in enumerate(lower_inputs))
        value = rng.randrange(2) if (address >> selected) & 1 else (lower_table >> lower_address) & 1
        upper_table |= value << address
    return {'ports': {'i': {'direction': 'input', 'bits': inputs},
                      'o': {'direction': 'output', 'bits': [100, 101]}},
            'netnames': {}, 'cells': {'logic.upper': lut(inputs, 100, upper_table),
                                      'logic.lower': lut(lower_inputs, 101, lower_table)}}


def output(cell, port, values):
    if cell['type'] == 'LUT6_2':
        width = 5 if port == 'O5' else 6
    else:
        width = int(cell['type'][-1])
    address = sum(values[cell['connections'][f'I{i}'][0]] << i for i in range(width))
    return (int(cell['parameters']['INIT'], 2) >> address) & 1


class CofactorTests(unittest.TestCase):
    def test_all_selected_inputs_and_lower_widths(self):
        for selected in range(6):
            for width in range(1, 6):
                with self.subTest(selected=selected, width=width):
                    module = example(selected, width)
                    before = copy.deepcopy(module)
                    report = fuse_module(module)
                    self.assertEqual(report['pair_count'], 1)
                    self.assertEqual(report['output_comparisons'], 128)
                    merged = module['cells']['logic.upper']
                    for address in range(64):
                        values = {bit: (address >> i) & 1 for i, bit in enumerate(range(10, 16))}
                        self.assertEqual(output(before['cells']['logic.upper'], 'O', values), output(merged, 'O6', values))
                        self.assertEqual(output(before['cells']['logic.lower'], 'O', values), output(merged, 'O5', values))

    def test_reject_one_wrong_truth_bit(self):
        module = example()
        old = int(module['cells']['logic.lower']['parameters']['INIT'], 2)
        module['cells']['logic.lower']['parameters']['INIT'] = f'{old ^ 1:032b}'
        before = copy.deepcopy(module)
        self.assertEqual(fuse_module(module)['pair_count'], 0)
        self.assertEqual(module, before)

    def test_constraints_and_undefined_tables(self):
        for side in ('logic.upper', 'logic.lower'):
            for key in ('BEL', 'LOC', 'keep', 'CONSTR_PARENT', 'unknown'):
                module = example()
                module['cells'][side]['attributes'][key] = '1'
                self.assertEqual(fuse_module(module)['pair_count'], 0, (side, key))
            module = example()
            table = module['cells'][side]['parameters']['INIT']
            module['cells'][side]['parameters']['INIT'] = 'x' + table[1:]
            self.assertEqual(fuse_module(module)['pair_count'], 0)

    def test_dedicated_consumers(self):
        for kind in ('CARRY4', 'MUXF7', 'MUXF8', 'RAM32M', 'SRL16E'):
            for bit in (100, 101):
                module = example()
                module['cells']['sink'] = {'type': kind, 'connections': {'I': [bit]},
                                            'port_directions': {'I': 'input'}}
                self.assertEqual(fuse_module(module)['pair_count'], 0, (kind, bit))

    def test_register_consumer_keeps_connections(self):
        module = example()
        sink = {'type': 'FDRE', 'connections': {'D': [101], 'C': [200], 'Q': [201]},
                'port_directions': {'D': 'input', 'C': 'input', 'Q': 'output'}, 'attributes': {}}
        module['cells']['register'] = copy.deepcopy(sink)
        self.assertEqual(fuse_module(module)['pair_count'], 1)
        self.assertEqual(module['cells']['register'], sink)

    def test_repeated_inputs_and_constants(self):
        for side in ('logic.upper', 'logic.lower'):
            module = example()
            module['cells'][side]['connections']['I1'] = module['cells'][side]['connections']['I0']
            self.assertEqual(fuse_module(module)['pair_count'], 0)
            module = example()
            module['cells'][side]['connections']['I0'] = ['0']
            self.assertEqual(fuse_module(module)['pair_count'], 0)

    def test_zero_limit(self):
        module = example()
        before = copy.deepcopy(module)
        self.assertEqual(fuse_module(module, 0)['pair_count'], 0)
        self.assertEqual(module, before)

    def test_normalized_irrelevant_input(self):
        self.assertEqual(function_key(0b1010, [10, 11]), function_key(0b10, [10]))
        self.assertEqual(function_key(0b1100, [11, 10]), function_key(0b10, [10]))

    def test_indirect_dependency_is_excluded(self):
        module = example(lower_width=1)
        module['cells']['middle'] = lut([101], 14, 0b10)
        module['ports']['i']['bits'].remove(14)
        before = copy.deepcopy(module)
        report = fuse_module(module)
        self.assertEqual(report['pair_count'], 0)
        self.assertGreater(report['excluded_cells']['combinational_dependency'], 0)
        self.assertEqual(module, before)

    def test_register_separates_dependencies(self):
        module = example(lower_width=1)
        module['cells']['register'] = {'type': 'FDRE', 'connections': {'D': [101], 'Q': [14]},
                                      'port_directions': {'D': 'input', 'Q': 'output'}}
        module['ports']['i']['bits'].remove(14)
        report = fuse_module(module)
        self.assertEqual(report['pair_count'], 1)
        self.assertTrue(report['combinational_dependencies_checked'])

    def test_clock_buffer_keeps_combinational_dependency(self):
        for kind in ('BUFG', 'BUFGCE', 'BUFH'):
            module = example(lower_width=1)
            module['cells']['buffer'] = {'type': kind, 'connections': {'I': [101], 'O': [14]},
                                        'port_directions': {'I': 'input', 'O': 'output'}}
            module['ports']['i']['bits'].remove(14)
            self.assertEqual(fuse_module(module)['pair_count'], 0)

    def test_previous_merge_updates_dependencies(self):
        cells = {'a': lut([10], 1, 2), 'b': lut([1], 2, 2),
                 'c': lut([11], 3, 2), 'd': lut([3], 4, 2)}
        graph = CombinationalDependencies(cells, {1: [('b', 'I0')], 3: [('d', 'I0')]})
        self.assertTrue(graph.independent('a', 'd'))
        self.assertTrue(graph.independent('b', 'c'))
        graph.merge('a', 'd')
        self.assertFalse(graph.independent('b', 'c'))

    def test_dsp_cascade_and_output_register_boundaries(self):
        for output, parameters, independent in [('P', {'PREG': 1}, True),
                                                 ('P', {'PREG': 0}, False),
                                                 ('ACOUT', {'PREG': 1, 'AREG': 0}, False),
                                                 ('ACOUT', {'PREG': 0, 'AREG': 1}, True)]:
            dsp = {'type': 'DSP48E1', 'parameters': parameters,
                   'connections': {'A': [1], output: [2]},
                   'port_directions': {'A': 'input', output: 'output'}}
            cells = {'a': lut([10], 1, 2), 'dsp': dsp, 'b': lut([2], 3, 2)}
            graph = CombinationalDependencies(cells, {1: [('dsp', 'A')], 2: [('b', 'I0')]})
            self.assertEqual(graph.independent('a', 'b'), independent)

    def test_single_use_lower(self):
        module = example()
        module['cells']['logic.upper_second'] = copy.deepcopy(module['cells']['logic.upper'])
        module['cells']['logic.upper_second']['connections']['O'] = [102]
        module['ports']['o']['bits'].append(102)
        self.assertEqual(fuse_module(module)['pair_count'], 1)
        self.assertIn('logic.upper_second', module['cells'])

    def test_cli_preserves_other_module(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            source = folder / 'mapped.json'
            original = {'modules': {'soc_top': example(), 'other': {'attributes': {'value': 'unchanged'}}}}
            source.write_text(json.dumps(original))
            subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'fuse_lut_cofactors.py'),
                            '--mapped', str(source), '--out', str(folder / 'fused.json'),
                            '--report', str(folder / 'report.json')], check=True, capture_output=True)
            result = json.loads((folder / 'fused.json').read_text())
            self.assertEqual(result['modules']['other'], original['modules']['other'])
            self.assertEqual(json.loads(source.read_text()), original)
            self.assertEqual(json.loads((folder / 'report.json').read_text())['pair_count'], 1)


if __name__ == '__main__':
    unittest.main()
