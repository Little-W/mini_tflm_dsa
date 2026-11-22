#!/usr/bin/env python3
"""检查完整连接图、物理目标独立状态和缺失报告处理；不调用 Vivado。"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / 'scripts/fpga/vivado_soc_results.py'
spec = importlib.util.spec_from_file_location('vivado_structural_results', HELPER)
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)


def timing_report(*, pulse='0.250', pulse_endpoints='400'):
    headers = ('WNS(ns)', 'TNS(ns)', 'TNS Failing Endpoints', 'TNS Total Endpoints',
               'WHS(ns)', 'THS(ns)', 'THS Failing Endpoints', 'THS Total Endpoints',
               'WPWS(ns)', 'TPWS(ns)', 'TPWS Failing Endpoints', 'TPWS Total Endpoints')
    values = ('0.125', '0.000', '0', '200', '0.100', '0.000', '0', '200',
              pulse, '0.000', '0', pulse_endpoints)
    return ' | Design Timing Summary\n' + '\n'.join(
        ''.join(f'{value:>24}  ' for value in row)
        for row in (headers, ('-' * 24,) * 12, values)) + '\n'


def graph_records(depth=10, *, control=False):
    rows = [['format', 'vivado_connectivity_v1'], ['scope', 'soc_top', 'top', 'soc_top', '0']]
    cells, pins = 0, 0

    def cell(name, kind, connections, parameters=None):
        nonlocal cells, pins
        cells += 1
        pins += len(connections)
        rows.append(['cell', name, kind, '0', str(len(connections))])
        rows.extend(['parameter', name, key, str(value)] for key, value in (parameters or {}).items())
        rows.extend(['pin', name, port, direction, net] for port, direction, net in connections)

    cell('constant1', 'VCC', [('P', 'OUT', 'one')])
    cell('constant0', 'GND', [('G', 'OUT', 'zero')])
    cell('source', 'FDRE', [('C', 'IN', 'clk'), ('D', 'IN', 'input'), ('CE', 'IN', 'one'),
                            ('R', 'IN', 'zero'), ('Q', 'OUT', 'n0')])
    for index in range(depth):
        cell('logic' + str(index), 'LUT1', [('I0', 'IN', f'n{index}'), ('O', 'OUT', f'n{index+1}')],
             {'INIT': "2'h2"})
    cell('sink', 'FDRE', [('C', 'IN', 'clk'), ('D', 'IN', 'n0' if control else f'n{depth}'),
                          ('CE', 'IN', f'n{depth}' if control else 'one'),
                          ('R', 'IN', 'zero'), ('Q', 'OUT', 'output')])
    rows.extend([['port', 'clk', 'IN', 'clk'], ['port', 'd', 'IN', 'input'],
                 ['port', 'q', 'OUT', 'output']])
    rows.append(['complete', str(cells), str(pins), '3'])
    return rows


def replace_graph_cell(rows, name, replacements):
    """将一个单元替换为给定结构，并重新列出导出数量。"""
    body = [row for row in rows if row[0] != 'complete' and
            not (row[0] in ('cell', 'parameter', 'pin') and row[1] == name)]
    for instance, kind, pins, parameters in replacements:
        body.append(['cell', instance, kind, '0', str(len(pins))])
        body.extend(['parameter', instance, key, str(value)] for key, value in parameters.items())
        body.extend(['pin', instance, port, direction, net] for port, direction, net in pins)
    body.append(['complete', *(str(sum(row[0] == kind for row in body)) for kind in ('cell', 'pin', 'port'))])
    return body


def dsp_graph_records(use_dport):
    parameters = {name: 0 for name in results.DSP_REGISTERS}
    parameters.update(A_INPUT='DIRECT', B_INPUT='DIRECT', USE_MULT='MULTIPLY',
                      USE_DPORT=use_dport, USE_SIMD='ONE48')
    pins = [('A', 'IN', 'zero'), ('B', 'IN', 'zero'), ('D', 'IN', 'n0'),
            ('CLK', 'IN', 'clk'), ('P', 'OUT', 'n1')]
    return replace_graph_cell(graph_records(2), 'logic0', [('logic0', 'DSP48E1', pins, parameters)])


def ram_macro_graph_records():
    shared = [('CLK', 'IN', 'clk'), ('I', 'IN', 'n0'), ('WE', 'IN', 'one')]
    macro = [('WCLK', 'IN', 'clk'), ('D', 'IN', 'n0'), ('WE', 'IN', 'one'),
             ('A0', 'IN', 'n0'), ('DPRA0', 'IN', 'n0'), ('DPO', 'OUT', 'n1'), ('SPO', 'OUT', 'unused_spo')]
    dp = shared + [('RADR0', 'IN', 'n0'), ('WADR0', 'IN', 'n0'), ('O', 'OUT', 'n1')]
    sp = shared + [('ADR0', 'IN', 'n0'), ('O', 'OUT', 'unused_spo')]
    return replace_graph_cell(graph_records(2), 'logic0', [
        ('logic0', 'RAM32X1D', macro, {}), ('logic0/DP', 'RAMD32', dp, {}), ('logic0/SP', 'RAMS32', sp, {})])


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vivado_coverage_')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def write_graph(self, rows):
        path = self.work / 'soc_top_connectivity.tsv'
        path.write_text(''.join('\t'.join(row) + '\n' for row in rows))
        return path

    def prepare(self, depth=10, count=45000, pulse='0.250', period='6.667', precise=True):
        self.write_graph(graph_records(depth))
        (self.work / 'manifest.json').write_text(json.dumps(dict(inputs=[], metadata={}, git={})))
        resources = [('Slice LUTs', count), ('LUT as Logic', count - 2000), ('LUT as Memory', 2000),
                     ('Slice Registers', 10000), ('Block RAM Tile', 5), ('RAMB36/FIFO', 4),
                     ('RAMB18', 2), ('DSPs', 256)]
        (self.work / 'soc_top_utilization.rpt').write_text(''.join(f'| {name} | {value} | 0 |\n' for name, value in resources))
        (self.work / 'soc_top_timing_summary.rpt').write_text(timing_report(pulse=pulse))
        (self.work / 'soc_top_endpoints.tsv').write_text(
            'delay_type\tclock\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n'
            'max\tclk\tsource/Q\tsink/D\t0.125\t2\n'
            'min\tclk\tsource/Q\tsink/D\t0.100\t1\n')
        header, clock = 'clock\tperiod_ns\tobject', f'clk\t{period}\tclk'
        if precise:
            header += '\tclock_kind\tdefinition_frequency_mhz\tdefinition_period_ns\tsource_pin\tsoc_clock_pin\tsame_source'
            clock += '\tprimary\t150.0\t6.666666666666667\tclk\tclk\t1'
        (self.work / 'soc_top_core_clock.tsv').write_text(header + '\n' + clock + '\n')
        (self.work / 'implementation_checks.tsv').write_text('check\tvalue\ncompleted\t1\npassed\t1\n')

    def summary(self, stage='routed'):
        return results.summarize(self.work / 'manifest.json', self.work, stage)

    def test_full_graph_depth_and_synchronous_control(self):
        for depth in (0, 10, 11, 22):
            for control in (False, True):
                with self.subTest(depth=depth, control=control):
                    value = results.connectivity(self.write_graph(graph_records(depth, control=control)))
                    self.assertTrue(value['graph_complete'])
                    self.assertEqual(value['longest_register_path_cells'], depth)

    def test_graph_rejects_partial_inventory_and_unknown_primitive(self):
        original = graph_records(2)
        for rows in (original[:-1], original[:3] + original[4:],
                     [row[:-1] if row[0] == 'complete' else row for row in original],
                     [row[:3] + ['1'] + row[4:] if row[:2] == ['cell', 'logic0'] else row for row in original],
                     [row for row in original if row[:3] != ['parameter', 'logic0', 'INIT']]):
            with self.subTest(rows=rows[:2]):
                with self.assertRaises(ValueError):
                    results.connectivity(self.write_graph(rows))
        unknown = [row[:2] + ['UNKNOWN_LOGIC'] + row[3:] if row[:2] == ['cell', 'logic0'] else row for row in original]
        self.assertFalse(results.connectivity(self.write_graph(unknown))['graph_complete'])

    def test_truncated_final_record_is_rejected(self):
        original = self.write_graph(graph_records(2)).read_bytes()
        for removed in (1, 2, 7, 25):
            with self.subTest(removed=removed):
                path = self.work / 'soc_top_connectivity.tsv'
                path.write_bytes(original[:-removed])
                with self.assertRaisesRegex(ValueError, 'did not finish'):
                    results.connectivity(path)

    def test_numeric_and_named_dsp_boolean_modes(self):
        for value, expected in ((0, 0), (1, 2), ('FALSE', 0), ('TRUE', 2)):
            with self.subTest(value=value):
                paths = results.connectivity(self.write_graph(dsp_graph_records(value)))
                self.assertTrue(paths['graph_complete'])
                self.assertEqual(paths['longest_register_path_cells'], expected)

    def test_combinational_cycle_is_not_complete(self):
        rows = graph_records(2)
        rows = [row[:4] + ['n2'] if row[:3] == ['pin', 'logic0', 'I0'] else row for row in rows]
        value = results.connectivity(self.write_graph(rows))
        self.assertFalse(value['graph_complete'])
        self.assertTrue(value['combinational_cycle_nodes'])

    def test_control_pin_and_connected_driver_are_required(self):
        rows = graph_records(2, control=True)
        rows = [row for row in rows if row[:3] != ['pin', 'sink', 'CE']]
        for row in rows:
            if row[:2] == ['cell', 'sink']:
                row[4] = str(int(row[4]) - 1)
            if row[0] == 'complete':
                row[2] = str(int(row[2]) - 1)
        with self.assertRaisesRegex(ValueError, 'pin inventory'):
            results.connectivity(self.write_graph(rows))
        rows = graph_records(2)
        rows = [row[:4] + ['missing_driver'] if row[:3] == ['pin', 'logic0', 'I0'] else row for row in rows]
        with self.assertRaisesRegex(ValueError, 'no exported driver'):
            results.connectivity(self.write_graph(rows))

    def test_missing_dsp_register_parameters_are_not_assumed(self):
        rows = graph_records(2)
        rows = [row[:2] + ['DSP48E1'] + row[3:] if row[:2] == ['cell', 'logic0'] else row for row in rows]
        with self.assertRaisesRegex(ValueError, 'DSP register'):
            results.connectivity(self.write_graph(rows))

    def test_targets_are_independent_and_sample_does_not_bound_depth(self):
        self.prepare(depth=11)
        value = self.summary()
        self.assertTrue(value['status']['slice_luts_within_limit'])
        self.assertTrue(value['status']['timing_150mhz_confirmed'])
        self.assertFalse(value['status']['all_connected_paths_within_limit'])
        self.assertFalse(value['status']['all_targets_met'])
        self.assertEqual(value['timing']['max']['sample']['maximum_observed_logic_levels'], 2)
        self.prepare(depth=10)
        self.assertTrue(self.summary()['status']['all_targets_met'])
        self.assertEqual(self.summary()['requirements']['combinational_logic_levels_maximum'], 10)
        self.prepare(depth=10, count=45001)
        value = self.summary()['status']
        self.assertFalse(value['slice_luts_within_limit'])
        self.assertTrue(value['all_connected_paths_within_limit'])
        self.assertFalse(value['all_targets_met'])

    def test_exact_clock_pulse_missing_data_and_synthesis_status(self):
        for period in ('6.666666666666667', '6.667'):
            self.prepare(period=period)
            self.assertTrue(self.summary()['status']['timing_150mhz_confirmed'])
        self.prepare(period='6.666', precise=False)
        self.assertTrue(self.summary()['status']['timing_150mhz_confirmed'])
        self.prepare(period='6.667', precise=False)
        self.assertIsNone(self.summary()['status']['timing_150mhz_confirmed'])
        for pulse, expected in (('-0.001', False), ('', None), ('NaN', None)):
            self.prepare(pulse=pulse)
            self.assertIs(self.summary()['status']['pulse_width_confirmed'], expected)
            self.assertIsNot(self.summary()['status']['all_targets_met'], True)
        self.prepare()
        (self.work / 'soc_top_connectivity.tsv').unlink()
        value = self.summary()['status']
        self.assertIsNone(value['all_connected_paths_within_limit'])
        self.assertIsNone(value['all_targets_met'])
        self.prepare()
        value = self.summary('synthesized')['status']
        self.assertTrue(value['all_connected_paths_within_limit'])
        self.assertIsNone(value['timing_150mhz_confirmed'])
        self.assertIsNone(value['all_targets_met'])

    def test_routed_cli_requires_every_target(self):
        for depth, count, expected in ((10, 44999, 0), (10, 45000, 0),
                                       (10, 45001, 1), (11, 45000, 1)):
            self.prepare(depth=depth, count=count)
            process = subprocess.run([sys.executable, str(HELPER), 'summarize', '--manifest',
                str(self.work / 'manifest.json'), '--directory', str(self.work), '--stage', 'routed'],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, expected, process.stderr)
            self.assertTrue((self.work / 'measurement.json').is_file())
            report = json.loads((self.work / 'measurement.json').read_text())
            self.assertEqual(report['requirements']['slice_luts_maximum'], 45000)
            self.assertEqual(report['status']['slice_luts_within_limit'], count <= 45000)

    def export_graph_model(self, *, board=False, unknown_inside=False, records=None, fail_export=False):
        script = self.work / 'export.tcl'
        cells = records or graph_records(2)
        scope = 'board_units/processor'
        if board:
            for row in cells:
                if row[0] in ('cell', 'pin', 'parameter') and row[1] not in ('constant0', 'constant1'):
                    row[1] = scope + '/' + row[1]
        if unknown_inside:
            for row in cells:
                if row[0] == 'cell' and row[2] == 'LUT1':
                    row[2] = 'UNKNOWN_LOGIC'
        values = {}
        cell_pins = {}
        pin_nets = {}
        cell_names = []
        port_names = []
        for row in cells:
            if row[0] == 'cell':
                name = row[1]
                cell_names.append(name)
                cell_pins[name] = []
                values[(name, 'NAME')] = name
                values[(name, 'REF_NAME')] = row[2]
                values[(name, 'IS_BLACKBOX')] = row[3]
            elif row[0] == 'parameter':
                values[(row[1], row[2])] = row[3]
            elif row[0] == 'pin':
                name = row[1] + '/' + row[2]
                cell_pins[row[1]].append(name)
                values[(name, 'REF_PIN_NAME')] = row[2]
                values[(name, 'DIRECTION')] = row[3]
                pin_nets[name] = row[4]
                values[(row[4], 'NAME')] = row[4]
            elif row[0] == 'port':
                name = scope + '/' + row[1] if board else row[1]
                port_names.append(name)
                values[(name, 'NAME')] = name
                values[(name, 'REF_PIN_NAME')] = row[1]
                values[(name, 'DIRECTION')] = row[2]
                pin_nets[name] = row[3]
                values[(row[3], 'NAME')] = row[3]
        def word(value):
            return '{' + str(value).replace('}', '\\}') + '}'
        values[('soc_top', 'NAME')] = 'soc_top'
        values[(scope, 'NAME')] = scope
        if board:
            cell_names.append('board_units/clock_generator')
            values[('board_units/clock_generator', 'NAME')] = 'board_units/clock_generator'
            values[('board_units/clock_generator', 'REF_NAME')] = 'MMCME2_ADV'
            cell_pins[scope] = port_names
        text = 'source [lindex $argv 0]\n'
        text += ''.join(f'dict set ::properties {word(o)} {word(p)} {word(v)}\n' for (o, p), v in values.items())
        text += ''.join(f'dict set ::pins {word(c)} {word(" ".join(p))}\n' for c, p in cell_pins.items())
        text += ''.join(f'dict set ::nets {word(p)} {word(n)}\n' for p, n in pin_nets.items())
        text += f'set ::cells {word(" ".join(cell_names))}\nset ::ports {word(" ".join(port_names))}\n'
        text += f'set ::soc_instance {word(scope)}\n'
        text += f'set ::fail_export {int(fail_export)}\n'
        text += '''proc current_design {} { return soc_top }
proc get_property {property object} { return [dict get $::properties $object $property] }
proc list_property {object} { return [dict keys [dict get $::properties $object]] }
proc get_cells {args} {
    if {$args eq {-hierarchical -filter {REF_NAME == soc_top || ORIG_REF_NAME == soc_top}}} {
        return $::soc_instance
    }
    if {$args ne {-hierarchical -filter {IS_PRIMITIVE == 1 || IS_BLACKBOX == 1}}} { error "Unexpected primitive query" }
    return $::cells
}
proc get_pins {args} { return [dict get $::pins [lindex $args 1]] }
proc get_ports {} { return $::ports }
proc get_nets {args} {
    if {[lrange $args 0 2] ne {-segments -top_net_of_hierarchical_group -of_objects}} { error "Hierarchy was not resolved" }
    if {$::fail_export && [string match *logic1/O [lindex $args 3]]} { error "Export stopped during pin enumeration" }
    return [dict get $::nets [lindex $args 3]]
}
soc_reports::write_connectivity [lindex $argv 1] [lindex $argv 2]
'''
        script.write_text(text)
        prefix = 'fpga_top' if board else 'soc_top'
        destination = self.work / f'{prefix}_connectivity.tsv'
        if fail_export:
            destination.write_text(''.join('\t'.join(row) + '\n' for row in graph_records(9)))
        result = subprocess.run(['tclsh', str(script), str(ROOT / 'scripts/fpga/vivado_soc_reports.tcl'),
                                 str(self.work), prefix], text=True, capture_output=True, timeout=10)
        if fail_export:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Export stopped during pin enumeration', result.stderr)
            self.assertFalse(destination.exists())
            self.assertFalse(destination.with_name(destination.name + '.tmp').exists())
            return None
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(destination.with_name(destination.name + '.tmp').exists())
        return results.connectivity(destination)

    def test_tcl_exports_every_pin_without_sampling(self):
        value = self.export_graph_model()
        self.assertTrue(value['graph_complete'])
        self.assertEqual(value['longest_register_path_cells'], 2)

    def test_tcl_exports_leaf_ram_cells(self):
        for board in (False, True):
            with self.subTest(board=board):
                value = self.export_graph_model(board=board, records=ram_macro_graph_records())
                self.assertTrue(value['graph_complete'])
                self.assertEqual(value['export_inventory']['cells'], 7)
                self.assertEqual(value['longest_register_path_cells'], 2)
                path = value['register_to_register_paths'][0]
                self.assertEqual(path['path'][0]['type'], 'RAMD32')
                self.assertEqual(path['startpoint']['cell'].rsplit('/', 1)[-1], 'source')

    def test_tcl_canonicalizes_dsp_boolean_parameters(self):
        for value, expected in ((0, 0), (1, 2)):
            with self.subTest(value=value):
                measured = self.export_graph_model(records=dsp_graph_records(value))
                self.assertTrue(measured['graph_complete'])
                self.assertEqual(measured['longest_register_path_cells'], expected)
                exported = (self.work / 'soc_top_connectivity.tsv').read_text()
                self.assertIn('\tUSE_DPORT\t' + ('TRUE' if value else 'FALSE') + '\n', exported)

    def test_failed_export_publishes_no_previous_or_partial_graph(self):
        for board in (False, True):
            with self.subTest(board=board):
                self.export_graph_model(board=board, fail_export=True)

    def test_board_exports_complete_soc_with_global_constants(self):
        value = self.export_graph_model(board=True)
        self.assertTrue(value['graph_complete'])
        self.assertEqual(value['longest_register_path_cells'], 2)
        self.assertEqual(value['design_scope'], dict(module='soc_top', kind='instance',
            name='board_units/processor', outside_primitive_cells=1, boundary_ports_complete=True))
        self.assertEqual(value['export_inventory']['cells'], 6)
        self.assertFalse(self.export_graph_model(board=True, unknown_inside=True)['graph_complete'])

    def test_soc_scope_and_complete_boundary_are_required(self):
        original = graph_records(2)
        for rows in (original[:1] + original[2:],
                     [row[:1] + ['cpu'] + row[2:] if row[0] == 'scope' else row for row in original],
                     [row[:-1] + ['1'] if row[0] == 'scope' else row for row in original]):
            with self.subTest(rows=rows[:2]):
                with self.assertRaises(ValueError):
                    results.connectivity(self.write_graph(rows))


if __name__ == '__main__':
    unittest.main()
