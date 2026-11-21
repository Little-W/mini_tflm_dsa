#!/usr/bin/env python3
"""使用 Tcl 命令模型检查 Vivado 脚本；不执行器件综合或实现。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROJECT = ROOT / 'fpga/vivado/tflm_ai_dsa_soc/scripts'
HELPER = PROJECT / 'timing_checks.tcl'
MAPPED = ROOT / 'scripts/fpga/vivado_implement_mapped_soc.tcl'
MOCK = HERE / 'vivado_timing_mock.tcl'
FILELIST = ROOT / 'veri/flist/dut_axil.f'
REQUIRED = ('no_clock', 'unconstrained_internal_endpoints', 'generated_clocks',
            'loops', 'latch_loops')


def tcl_word(value):
    """将测试数据作为一个 Tcl 字符串传入，禁止命令或变量替换。"""
    text = str(value).replace('\\', '\\\\').replace('$', '\\$').replace('[', '\\[')
    return '"' + text.replace('"', '\\"').replace('\n', '\\n').replace('\r', '\\r') + '"'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def report_text(*, style='modern', counts=None, missing=None, roots=False):
    """构造 check_timing 文字格式；所有数量均来自测试输入。"""
    counts = counts or {}
    bodies = {
        'no_clock': 'register/latch pins with no clock.',
        'unconstrained_internal_endpoints': 'pins that are not constrained for maximum delay.',
        'generated_clocks': 'generated clocks that are not connected to a clock source.',
        'loops': 'combinational loops in the design.',
        'latch_loops': 'latch loops in the design.',
    }

    def header(index, name):
        if style == 'modern':
            return f'{index}. checking {name} ({counts.get(name, 0)})'
        if style == 'numbered':
            return f'{index}. checking {name}'
        return f'Checking {name}.'

    lines = ['check_timing: synthetic input for script verification']
    if style == 'modern':
        lines += ['Table of Contents', *[header(i, name) for i, name in enumerate(REQUIRED, 1)]]
    for index, name in enumerate(REQUIRED, 1):
        lines += ['', header(index, name), '-' * 40]
        if name == missing:
            continue
        count = counts.get(name, 0)
        lines.append(f'There {"is" if count == 1 else "are"} {count} {bodies[name]}')
        if name == 'unconstrained_internal_endpoints':
            lines.append('There are 0 pins with constant clock.')
        if roots and name == 'no_clock':
            lines.append('There are 2 register/latch pins with no clock driven by root synthetic_root.')
    return '\n'.join(lines) + '\n'


def set_option(name, value):
    return f'vivado_timing_mock::set_option {tcl_word(name)} {tcl_word(value)}\n'


class TimingTests(unittest.TestCase):
    directory: Path
    tclsh: str
    picorv32: Path | None
    cases = []

    def setUp(self):
        self.work = self.directory / 'cases' / self._testMethodName
        if self.work.exists():
            shutil.rmtree(self.work)
        self.work.mkdir(parents=True, exist_ok=True)

    def execute(self, name, script, *, success=True, environment=None):
        case = self.work / name
        case.mkdir(parents=True, exist_ok=True)
        runner = case / 'run.tcl'
        runner.write_text(script)
        result = subprocess.run([self.tclsh, str(runner)], cwd=ROOT, env=environment,
                                text=True, capture_output=True, timeout=60)
        (case / 'stdout.log').write_text(result.stdout)
        (case / 'stderr.log').write_text(result.stderr)
        self.cases.append(dict(test=self._testMethodName, case=name,
                               expected_accept=success, accepted=result.returncode == 0,
                               command_model_only=True))
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)
        return case, result

    def run_helper(self, name, configuration='', *, success=True):
        case = self.work / name
        output = case / 'synthetic_reports'
        script = f'''source {tcl_word(MOCK)}
{configuration}
source {tcl_word(HELPER)}
set status [catch {{timing_checks::check_implementation {tcl_word(output)}}} message options]
vivado_timing_mock::save_events {tcl_word(case / 'calls.tcllist')}
if {{$status}} {{ puts stderr [dict get $options -errorinfo]; exit 1 }}
puts TIMING_COMMAND_MODEL_PASS
'''
        path, result = self.execute(name, script, success=success)
        return output, path, result

    def table(self, path, name):
        with (path / name).open(newline='') as stream:
            return list(csv.DictReader(stream, delimiter='\t'))

    def clock_rows(self, path):
        return {row['clock']: row for row in self.table(path, 'synchronous_timing.tsv')}

    def status_values(self, path):
        return {row['check']: row['value'] for row in self.table(path, 'implementation_checks.tsv')}

    def test_check_timing_text_formats(self):
        for style in ('modern', 'numbered', 'plain'):
            with self.subTest(style=style):
                output, _, _ = self.run_helper(style, set_option('check_report', report_text(style=style)))
                counts = {row['check']: int(row['count']) for row in self.table(output, 'internal_timing_checks.tsv')}
                self.assertEqual(counts, dict.fromkeys(REQUIRED, 0))

    def test_check_timing_singular_and_multiple_roots(self):
        report = report_text(counts={'no_clock': 1}, roots=True)
        output, _, result = self.run_helper('root_counts', set_option('check_report', report), success=False)
        counts = {row['check']: int(row['count']) for row in self.table(output, 'internal_timing_checks.tsv')}
        self.assertEqual(counts['no_clock'], 3)
        self.assertIn("'no_clock' found 3", result.stderr)

    def test_every_required_check_rejects_nonzero_count(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                output, _, result = self.run_helper(name, set_option('check_report', report_text(counts={name: 1})), success=False)
                self.assertIn(f"'{name}' found 1", result.stderr)
                self.assertEqual(self.status_values(output)['passed'], '0')

    def test_check_timing_missing_body_fails(self):
        for name in REQUIRED:
            with self.subTest(name=name):
                _, _, result = self.run_helper(name, set_option('check_report', report_text(missing=name)), success=False)
                self.assertIn('No numeric result', result.stderr)
                self.assertIn(name, result.stderr)

    def test_route_completion_and_errors(self):
        for name, configuration, expected in (
            ('unrouted', set_option('fully_routed', 0), ('0', '0')),
            ('partially_routed', set_option('fully_routed', 0), ('0', '0')),
            ('route_error', set_option('routing_errors', 1), ('1', '1')),
            ('unknown_status', set_option('fully_routed', ''), ('', '0')),
        ):
            with self.subTest(name=name):
                output, _, result = self.run_helper(name, configuration, success=False)
                values = self.status_values(output)
                self.assertEqual((values['fully_routed'], values['routing_errors']), expected)
                self.assertEqual(values['passed'], '0')
                self.assertIn('incomplete or erroneous routing', result.stderr)

    def test_complete_pulse_statistics_and_missing_summary(self):
        cases = (
            ('pulse_violation', 'vivado_timing_mock::set_option timing_summary '
             '[string map {0.250 -0.250} [vivado_timing_mock::default_timing_summary]]\n'),
            ('missing_global_summary', set_option('timing_summary', 'Unavailable')),
        )
        for name, configuration in cases:
            with self.subTest(name=name):
                output, _, result = self.run_helper(name, configuration, success=False)
                self.assertEqual(self.status_values(output)['complete_global_timing'], '0')
                self.assertEqual(self.status_values(output)['passed'], '0')
                self.assertIn('Complete setup, hold or pulse-width statistics', result.stderr)

    def test_drc_severity_selection(self):
        for severity, rule in (('fatal', 'DRC_FATAL'), ('error', 'DRC_ERROR'), ('critical_warning', 'DRC_CRITICAL')):
            with self.subTest(severity=severity):
                output, _, result = self.run_helper(severity, set_option('drc_failures', rule), success=False)
                self.assertIn('Required post-route DRC checks failed', result.stderr)
                self.assertEqual(self.status_values(output)['severe_drc_violations'], '1')
        output, _, _ = self.run_helper('advisory', set_option('drc_failures', 'DRC_WARNING DRC_ADVISORY'))
        self.assertEqual(self.status_values(output)['severe_drc_violations'], '0')
        _, _, result = self.run_helper('empty_selection', set_option('no_drc_checks', 1), success=False)
        self.assertIn('No required post-route DRC checks', result.stderr)

    def test_bounded_worst_path_queries(self):
        configuration = '''vivado_timing_mock::clear_paths
vivado_timing_mock::set_option max_path_query_limit 1
vivado_timing_mock::set_clock aux_clk 10.0
for {set index 0} {$index < 1105} {incr index} {
    vivado_timing_mock::add_path setup_$index max endpoint_$index/D 0.1 soc_clk soc_clk 6.667
    vivado_timing_mock::add_path hold_$index min endpoint_$index/D 0.25 soc_clk soc_clk 0
}
vivado_timing_mock::add_path aux_setup max aux/D 0.4 aux_clk aux_clk 10.0
vivado_timing_mock::add_path aux_hold min aux/D 0.2 aux_clk aux_clk 0
'''
        output, case, _ = self.run_helper('bounded', configuration)
        status = self.status_values(output)
        self.assertEqual(status['passed'], '1')
        self.assertEqual((status['setup_endpoints'], status['hold_endpoints']),
                         ('unavailable', 'unavailable'))
        self.assertEqual((status['clocks_with_setup_paths'], status['clocks_with_hold_paths']), ('2', '2'))
        rows = self.clock_rows(output)
        for clock, setup, hold in (('soc_clk', 0.1, 0.25), ('aux_clk', 0.4, 0.2)):
            row = rows[clock]
            self.assertAlmostEqual(float(row['setup_wns_ns']), setup)
            self.assertAlmostEqual(float(row['hold_wns_ns']), hold)
            for field in ('setup_tns_ns', 'setup_endpoints', 'setup_failing_endpoints',
                          'hold_tns_ns', 'hold_endpoints', 'hold_failing_endpoints',
                          'single_cycle_setup_fmax_estimate_mhz'):
                self.assertEqual(row[field], 'unavailable', field)
            self.assertEqual(row['fmax_status'], 'unavailable_bounded_path_sampling')
        calls = (case / 'calls.tcllist').read_text().splitlines()
        queries = [line for line in calls if line.startswith('get_timing_paths ')]
        for clock in ('soc_clk', 'aux_clk'):
            for delay in ('max', 'min'):
                selected = [line for line in queries if f'-delay_type {delay} ' in line
                            and f'-to {clock} ' in line]
                self.assertEqual(len(selected), 1, queries)
                self.assertIn('-max_paths 1 ', selected[0])
                self.assertIn('-nworst 1 ', selected[0])
        self.assertTrue(all('-max_paths 1 ' in line for line in queries), queries)

    def test_negative_setup_and_hold_slack_fail(self):
        for delay in ('max', 'min'):
            for capture in ('soc_clk', '{}'):
                with self.subTest(delay=delay, capture=capture):
                    configuration = f'vivado_timing_mock::add_path bad {delay} bad/D -0.2 soc_clk {capture} 6.667\n'
                    output, _, result = self.run_helper(delay + ('_global' if capture == '{}' else '_clock'),
                                                        configuration, success=False)
                    self.assertEqual(self.status_values(output)['passed'], '0')
                    self.assertIn('negative', result.stderr.lower())
                    if capture == '{}':
                        self.assertIn(f'negative {delay} timing slack', result.stderr)

    def test_absent_setup_or_hold_paths_fail(self):
        for name, configuration in (
            ('no_paths', 'vivado_timing_mock::clear_paths\n'),
            ('setup_only', 'dict unset ::vivado_timing_mock::paths hold_default\n'),
            ('hold_only', 'dict unset ::vivado_timing_mock::paths setup_default\n'),
            ('no_clocks', 'set ::vivado_timing_mock::clocks [dict create]\n'),
            ('second_clock_setup_only', '''vivado_timing_mock::set_clock aux_clk 10.0
vivado_timing_mock::add_path auxiliary max endpoint_aux/D 1.0 aux_clk aux_clk 10.0
'''),
            ('second_clock_hold_only', '''vivado_timing_mock::set_clock aux_clk 10.0
vivado_timing_mock::add_path auxiliary min endpoint_aux/D 0.5 aux_clk aux_clk 0
'''),
        ):
            with self.subTest(name=name):
                output, _, _ = self.run_helper(name, configuration, success=False)
                self.assertEqual(self.status_values(output)['passed'], '0')

    def test_invalid_numeric_properties_fail(self):
        cases = []
        for value in ('NaN', 'Inf', '-Inf', '1e309', ''):
            cases.append((f'slack_{value or "empty"}', f'dict set ::vivado_timing_mock::paths setup_default SLACK {tcl_word(value)}\n'))
            cases.append((f'period_{value or "empty"}', f'vivado_timing_mock::set_clock soc_clk {tcl_word(value)}\n'))
        for value in ('0', '-1'):
            cases.append((f'period_{value}', f'vivado_timing_mock::set_clock soc_clk {value}\n'))
        for name, configuration in cases:
            with self.subTest(name=name):
                _, _, result = self.run_helper(name, configuration, success=False)
                self.assertTrue(any(text in result.stderr for text in ('finite numeric', 'must be positive', 'no ENDPOINT_PIN')), result.stderr)

    def run_mapped(self, name, *, period='6.667', configuration='', success=True, xdc=True):
        case = self.work / name
        case.mkdir(parents=True, exist_ok=True)
        mapped = case / 'synthetic_mapped.v'
        mapped.write_text('// Tcl command model input; no implemented netlist.\nmodule soc_top(input clk); endmodule\n')
        constraints = case / 'synthetic_input.xdc'
        constraints.write_text(f'create_clock -name soc_clk -period {tcl_word(period)} [get_ports clk]\n' if xdc else '')
        output = case / 'synthetic_reports'
        script = f'''source {tcl_word(MOCK)}
set ::vivado_timing_mock::clocks [dict create]
vivado_timing_mock::set_option input_clocks {{}}
{configuration}
set argv [list {tcl_word(mapped)} {tcl_word(constraints)} {tcl_word(output)}]
set status [catch {{source {tcl_word(MAPPED)}}} message options]
vivado_timing_mock::save_events {tcl_word(case / 'calls.tcllist')}
if {{$status}} {{ puts stderr [dict get $options -errorinfo]; exit 1 }}
puts MAPPED_COMMAND_MODEL_PASS
'''
        path, result = self.execute(name, script, success=success)
        return output, path, result

    def test_mapped_entry_clock_period_and_call_order(self):
        for name, period, xdc in (('target', '6.667', True), ('stricter', '6.0', True), ('created', '6.667', False)):
            with self.subTest(name=name):
                output, case, _ = self.run_mapped(name, period=period, xdc=xdc)
                self.assertIn(f'Clock period ns: {period}', (output / 'inputs.txt').read_text())
                calls = (case / 'calls.tcllist').read_text().splitlines()
                commands = [line.split()[0] for line in calls]
                ordered = ['read_verilog', 'read_xdc', 'link_design', 'opt_design', 'place_design', 'phys_opt_design', 'route_design']
                positions = [commands.index(command) for command in ordered]
                self.assertEqual(positions, sorted(positions))
                self.assertLess(commands.index('route_design'), calls.index('report_route_status -boolean_check ROUTED_FULLY'))
                routed_summary = next(i for i, line in enumerate(calls)
                                      if line.startswith('report_timing_summary ') and 'routed_timing.rpt' in line)
                self.assertLess(commands.index('route_design'), routed_summary)
                self.assertLess(routed_summary, calls.index('report_route_status -boolean_check ROUTED_FULLY'))
                self.assertLess(calls.index('report_route_status -boolean_check ROUTED_FULLY'), commands.index('write_xdc'))
                self.assertEqual(commands.count('create_clock'), 1)
                self.assertNotIn('write_bitstream', commands)
                self.assertEqual(self.status_values(output)['passed'], '1')

    def test_mapped_entry_rejects_invalid_clock_periods_before_implementation(self):
        for period in ('7', '0', '-1', 'NaN', 'Inf', '1e309'):
            with self.subTest(period=period):
                _, case, _ = self.run_mapped('period_' + period, period=period, success=False)
                self.assertNotIn('opt_design', (case / 'calls.tcllist').read_text().splitlines())

    def test_mapped_entry_rejects_ambiguous_ports_and_clocks(self):
        configurations = (
            ('missing_port', set_option('clock_ports', '')),
            ('multiple_ports', set_option('clock_ports', 'clk clk_duplicate')),
            ('multiple_clocks', '''rename create_clock create_clock_original
proc create_clock {args} {
    create_clock_original {*}$args
    vivado_timing_mock::set_clock auxiliary_clock 6.0
    vivado_timing_mock::set_option input_clocks {soc_clk auxiliary_clock}
}
'''),
        )
        for name, configuration in configurations:
            with self.subTest(name=name):
                _, case, _ = self.run_mapped(name, configuration=configuration, success=False)
                self.assertNotIn('opt_design', (case / 'calls.tcllist').read_text().splitlines())

    def test_mapped_entry_invokes_required_checks(self):
        _, case, result = self.run_mapped('incomplete_route', configuration=set_option('fully_routed', 0), success=False)
        self.assertIn('incomplete or erroneous routing', result.stderr)
        calls = (case / 'calls.tcllist').read_text()
        self.assertIn('report_route_status -boolean_check ROUTED_FULLY', calls)
        self.assertIn('check_timing -verbose -override_defaults', calls)
        self.assertIn('write_xdc -force -constraints valid -type timing', calls)

    def test_production_source_list_covers_dut_axil(self):
        environment = dict(os.environ)
        if self.picorv32:
            environment['PICORV32_ROOT'] = str(self.picorv32)
        script = f'''source {tcl_word(PROJECT / 'sources.tcl')}
foreach path $design_sources {{ puts "SOURCE\\t[file normalize $path]" }}
foreach path $include_dirs {{ puts "INCLUDE\\t[file normalize $path]" }}
'''
        case, result = self.execute('source_list', script, environment=environment)
        actual = [Path(line.split('\t', 1)[1]) for line in result.stdout.splitlines() if line.startswith('SOURCE\t')]
        self.assertEqual(len(actual), len(set(actual)), 'Vivado source list contains duplicate paths')
        required, includes = [], []
        for line in FILELIST.read_text().splitlines():
            line = line.split('//', 1)[0].strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('+incdir+'):
                includes.append((FILELIST.parent / line[len('+incdir+'):]).resolve())
            else:
                required.append((FILELIST.parent / line).resolve())
        excluded = {ROOT / 'rtl/axi_top/axil_top_with_ram.sv'}
        self.assertTrue(excluded.issubset(set(required)))
        required = set(required) - excluded
        self.assertTrue(required.issubset(set(actual)), '\n'.join(str(path) for path in sorted(required - set(actual))))
        self.assertTrue(all(path.is_file() for path in actual))
        actual_includes = {Path(line.split('\t', 1)[1]) for line in result.stdout.splitlines() if line.startswith('INCLUDE\t')}
        self.assertTrue(set(includes).issubset(actual_includes))
        self.assertIn(ROOT / 'rtl/soc_top.sv', actual)
        report = dict(command_model_only=True, dut_axil_sources=len(required),
                      vivado_sources=len(actual), excluded_simulation_wrappers=sorted(map(str, excluded)),
                      required_sources=sorted(map(str, required)), vivado_source_sha256={str(path): digest(path) for path in actual})
        (case / 'source_coverage.json').write_text(json.dumps(report, indent=2) + '\n')

    def test_tcl_scripts_are_complete(self):
        sources = [*sorted(PROJECT.glob('*.tcl')), MAPPED, MOCK]
        items = ' '.join(tcl_word(path) for path in sources)
        script = f'''foreach path [list {items}] {{
    set stream [open $path r]
    set text [read $stream]
    close $stream
    if {{![info complete $text]}} {{ error "Incomplete Tcl syntax: $path" }}
    puts "COMPLETE\\t$path"
}}
'''
        _, result = self.execute('complete', script)
        self.assertEqual(sum(line.startswith('COMPLETE\t') for line in result.stdout.splitlines()), len(sources))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tclsh', default='tclsh')
    parser.add_argument('--picorv32', type=Path, default=os.environ.get('PICORV32_ROOT'))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    TimingTests.directory = out
    TimingTests.tclsh = args.tclsh
    TimingTests.picorv32 = args.picorv32.resolve() if args.picorv32 else None
    TimingTests.cases = []
    sources = [*sorted(PROJECT.glob('*.tcl')), MAPPED, MOCK, Path(__file__).resolve(), FILELIST]
    before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    started = time.monotonic()
    with (out / 'test.log').open('w') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(TimingTests))
    after = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    report = dict(passed=result.wasSuccessful() and before == after, tests=result.testsRun,
                  tcl_processes=len(TimingTests.cases), elapsed_seconds=time.monotonic() - started,
                  actual_vivado_executed=False, synthesis_executed=False, implementation_executed=False,
                  timing_data='Synthetic command-model inputs used only to test Tcl control flow and report arithmetic',
                  source_sha256=before, source_unchanged=before == after, cases=TimingTests.cases)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'tests', 'tcl_processes', 'elapsed_seconds', 'actual_vivado_executed')}))
    if not report['passed']:
        print((out / 'test.log').read_text(), file=sys.stderr)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
