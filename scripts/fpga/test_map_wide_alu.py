#!/usr/bin/env python3
"""Check DSP budget and register-boundary candidate selection."""
import unittest
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from map_wide_alu import next_autoidx, retain_as_carry, select_cells


def cell(kind, inputs, outputs, width=32, preg=0):
    ports = {'A': inputs, 'B': ['0'] * width, 'Y': outputs}
    return {'type': kind, 'parameters': {'Y_WIDTH': width, 'PREG': preg},
            'connections': ports, 'port_directions': {'A': 'input', 'B': 'input', 'Y': 'output'}}


class SelectWideAluTests(unittest.TestCase):
    def test_checkpoint_counter_covers_private_names(self):
        design = {'modules': {'top': {'cells': {'$auto$some.cc:2:step$170': {}},
                                     'netnames': {'$generated$902.middle': {}, 'public99999': {}},
                                     'ports': {'a': {}}}}}
        self.assertEqual(next_autoidx(design), 903)

    def test_checkpoint_counter_range(self):
        self.assertEqual(next_autoidx({'modules': {'top': {}}}), 1)
        with self.assertRaises(ValueError):
            next_autoidx({'modules': {'top': {'cells': {'$auto$2147483647': {}}}}})

    def test_independent_cells_fit_budget(self):
        module = {'cells': {f'alu{index}': cell('$alu', [index], [index + 100]) for index in range(5)}}
        result = select_cells(module, 3, reserve=1)
        self.assertEqual(result['additional_dsp_cells'], 2)

    def test_fabric_path_prevents_dsp_chain(self):
        module = {'cells': {'a': cell('$alu', [1], [2]), 'mux': cell('$mux', [2], [3]),
                            'b': cell('$alu', [3], [4])}}
        self.assertEqual(select_cells(module, 10)['additional_dsp_cells'], 1)

    def test_register_separates_selected_dsp_cells(self):
        module = {'cells': {'a': cell('$alu', [1], [2]), 'ff': cell('$sdffe', [2], [3]),
                            'b': cell('$alu', [3], [4])}}
        self.assertEqual(select_cells(module, 10)['additional_dsp_cells'], 2)

    def test_two_dsp_limit_stops_a_three_cell_chain(self):
        module = {'cells': {'a': cell('$alu', [1], [2]),
                            'b': cell('$alu', [2], [3]),
                            'c': cell('$alu', [3], [4])}}
        result = select_cells(module, 10, maximum_chain=2)
        self.assertEqual(result['additional_dsp_cells'], 2)
        self.assertEqual(result['selected_combinational_dsp_upper_bound'], 2)

    def test_parallel_ancestors_do_not_form_an_extra_stage(self):
        module = {'cells': {'a': cell('$alu', [1], [2]),
                            'b': cell('$alu', [3], [4]),
                            'c': cell('$alu', [2, 4], [5])}}
        result = select_cells(module, 10, maximum_chain=2)
        self.assertEqual(result['additional_dsp_cells'], 3)
        self.assertEqual(result['selected_combinational_dsp_upper_bound'], 2)

    def test_limit_checks_both_ancestors_and_descendants(self):
        module = {'cells': {'z_middle': cell('$alu', [2], [3], width=24),
                            'a_first': cell('$alu', [1], [2], width=32),
                            'b_last': cell('$alu', [3], [4], width=32)}}
        result = select_cells(module, 10, maximum_chain=2)
        self.assertEqual([v['cell'] for v in result['selected']], ['a_first', 'b_last'])

    def test_two_selected_limit_preserves_existing_dsp_separation(self):
        module = {'cells': {'before': cell('$alu', [1], [2]), 'dsp': cell('DSP48E1', [2], [3]),
                            'after': cell('$alu', [3], [4]), 'independent': cell('$alu', [5], [6])}}
        result = select_cells(module, 10, maximum_chain=2)
        self.assertEqual([item['cell'] for item in result['selected']], ['independent'])

    def test_existing_dsp_blocks_both_directions(self):
        module = {'cells': {'before': cell('$alu', [1], [2]), 'dsp': cell('DSP48E1', [2], [3]),
                            'after': cell('$alu', [3], [4]), 'independent': cell('$alu', [5], [6])}}
        result = select_cells(module, 10)
        self.assertEqual([item['cell'] for item in result['selected']], ['independent'])
        self.assertEqual(result['resulting_dsp_cells'], 2)

    def test_registered_dsp_output_breaks_path(self):
        module = {'cells': {'dsp': cell('DSP48E1', [1], [2], preg=1), 'alu': cell('$alu', [2], [3])}}
        self.assertEqual(select_cells(module, 2)['additional_dsp_cells'], 1)

    def test_existing_budget_checked(self):
        with self.assertRaises(ValueError):
            select_cells({'cells': {'dsp': cell('DSP48E1', [1], [2])}}, 1, reserve=1)

    def test_cycle_is_rejected(self):
        with self.assertRaises(ValueError):
            select_cells({'cells': {'a': cell('$alu', [1], [2]), 'b': cell('$alu', [2], [1])}}, 2)

    def test_narrow_candidates_preserve_wide_selection(self):
        module = {'cells': {'wide': cell('$alu', [1], [2], width=24),
                            'narrow': cell('$alu', list(range(10, 26)), [30], width=16)}}
        result = select_cells(module, 1, minimum_width=16)
        self.assertEqual([item['cell'] for item in result['selected']], ['wide'])
        result = select_cells(module, 2, minimum_width=16)
        self.assertEqual([item['cell'] for item in result['selected']], ['wide', 'narrow'])

    def test_narrow_dependency_does_not_displace_wide_cell(self):
        module = {'cells': {'wide': cell('$alu', [30], [2], width=24),
                            'narrow': cell('$alu', list(range(10, 26)), [30], width=16)}}
        result = select_cells(module, 2, minimum_width=16)
        self.assertEqual([item['cell'] for item in result['selected']], ['wide'])

    def test_retained_cell_preserves_remaining_selection(self):
        module = {'cells': {f'alu{index}': cell('$alu', [index], [index + 100]) for index in range(5)}}
        reference = select_cells(module, 3)
        result = retain_as_carry(copy.deepcopy(reference), reference, ['alu1'])
        self.assertEqual([item['cell'] for item in result['selected']], ['alu0', 'alu2'])
        self.assertEqual([item['cell'] for item in result['retained_as_carry']], ['alu1'])
        self.assertEqual(result['resulting_dsp_cells'], 2)
        self.assertEqual(reference['additional_dsp_cells'], 3)

    def test_retained_cell_requires_original_selection(self):
        module = {'cells': {f'alu{index}': cell('$alu', [index], [index + 100]) for index in range(3)}}
        reference = select_cells(module, 2)
        for names in (['missing'], ['alu2'], ['alu0', 'alu0']):
            with self.assertRaises(ValueError):
                retain_as_carry(copy.deepcopy(reference), reference, names)
        changed = select_cells(module, 3)
        with self.assertRaises(ValueError):
            retain_as_carry(changed, reference, ['alu0'])

    def test_cli_preserves_netlist_and_checks_input_digest(self):
        module = {'cells': {f'alu{index}': cell('$alu', [index], [index + 100]) for index in range(3)},
                  'ports': {}, 'netnames': {}, 'attributes': {'top': 1}}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder / 'input.json'
            source.write_text(json.dumps({'modules': {'top': module}}))
            script = Path(__file__).with_name('map_wide_alu.py')
            command = [sys.executable, str(script), '--input', str(source), '--top', 'top', '--budget', '2']
            reference, candidate = folder / 'reference.json', folder / 'candidate.json'
            reference_report, candidate_report = folder / 'reference_report.json', folder / 'candidate_report.json'
            subprocess.run(command + ['--output', str(reference), '--report', str(reference_report)],
                           check=True, capture_output=True, text=True)
            candidate_command = command + ['--output', str(candidate), '--report', str(candidate_report),
                                           '--selection-reference', str(reference_report), '--keep-as-carry', 'alu0']
            subprocess.run(candidate_command, check=True, capture_output=True, text=True)
            expected = json.loads(reference.read_text())
            expected['modules']['top']['cells']['alu0']['type'] = '$alu'
            self.assertEqual(json.loads(candidate.read_text()), expected)
            self.assertEqual(json.loads(candidate_report.read_text())['additional_dsp_cells'], 1)
            self.assertEqual(reference.with_suffix('.autoidx.il').read_bytes(),
                             candidate.with_suffix('.autoidx.il').read_bytes())
            before = candidate.read_bytes()
            source.write_text(source.read_text() + '\n')
            rejected = subprocess.run(candidate_command, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn('input differs', rejected.stderr)
            self.assertEqual(candidate.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
