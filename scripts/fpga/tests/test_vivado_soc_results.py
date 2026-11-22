#!/usr/bin/env python3
"""用人工构造的报告和 Tcl 命令模型检查原生 Vivado 测量流程。"""
import csv
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / 'scripts/fpga/vivado_soc_results.py'
spec = importlib.util.spec_from_file_location('vivado_soc_results', HELPER)
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)

UTILIZATION = '''
| Site Type | Used | Fixed | Available | Util% |
| Slice LUTs* | 58,210 | 0 | 134600 | 43.25 |
| LUT as Logic | 56,075 | 0 | 134600 | 41.66 |
| LUT as Memory | 2,135 | 0 | 46200 | 4.62 |
| Slice Registers | 37,766 | 0 | 269200 | 14.03 |
| Block RAM Tile | 130 | 0 | 365 | 35.62 |
| RAMB36/FIFO | 111 | 0 | 365 | 30.41 |
| RAMB18 | 38 | 0 | 730 | 5.21 |
| DSPs | 320 | 0 | 740 | 43.24 |
'''


class ResultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vivado_results_')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def test_vivado_resource_units(self):
        value = results.utilization(UTILIZATION)
        self.assertEqual(value['slice_luts'], 58210)
        self.assertEqual(value['memory_luts'], 2135)
        self.assertEqual(value['slice_registers'], 37766)
        self.assertEqual(value['bram_tiles'], 130)
        self.assertEqual(value['ramb36'], 111)
        self.assertEqual(value['ramb18'], 38)

    def test_missing_and_inconsistent_resources(self):
        for text in (UTILIZATION.replace('| DSPs', '| Unrelated'),
                     UTILIZATION.replace('58,210', '58,211'),
                     UTILIZATION.replace('| 130 |', '| 129.5 |')):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    results.utilization(text)

    def test_fractional_bram_tile(self):
        value = results.utilization(UTILIZATION.replace('| 130 |', '| 130.5 |').replace('| 38 |', '| 39 |'))
        self.assertEqual(value['bram_tiles'], 130.5)

    def test_inputs_are_verified_by_content(self):
        source = self.work / 'source with spaces.sv'
        source.write_text('module source; endmodule\n')
        include = self.work / 'include'
        include.mkdir()
        header = include / 'settings.svh'
        header.write_text('`define WIDTH 16\n')
        records = self.work / 'inputs.tsv'
        records.write_text(f'repository\t{self.work}\nsource\t{source}\ninclude_dir\t{include}\n')
        manifest = self.work / 'manifest.json'
        results.snapshot(records, manifest)
        self.assertEqual(len(results.verify(manifest)['inputs']), 2)
        header.write_text('`define WIDTH 32\n')
        with self.assertRaisesRegex(ValueError, 'settings.svh'):
            results.verify(manifest)

    def test_snapshot_rejects_missing_input(self):
        records = self.work / 'inputs.tsv'
        records.write_text(f'repository\t{self.work}\nsource\t{self.work}/missing.sv\n')
        with self.assertRaises(ValueError):
            results.snapshot(records, self.work / 'manifest.json')

    def test_endpoint_statistics_are_sampled_paths_not_totals(self):
        report = self.work / 'endpoints.tsv'
        report.write_text('delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n'
                          'max\tclk\t6.667\ta/Q\tx/D\t-4.536\t16\n'
                          'max\tclk\t6.667\tb/Q\tx/D\t-1.0\t9\n'
                          'max\tclk\t6.667\tc/Q\ty/D\t-2.0\t12\n'
                          'max\tclk\t6.667\td/Q\tz/D\t0.5\t8\n'
                          'min\tclk\t6.667\te/Q\tz/D\t0.1\t2\n')
        value = results.endpoint_statistics(report)
        self.assertEqual(value['max']['sampled_paths'], 4)
        self.assertNotIn('tns_ns', value['max'])
        self.assertNotIn('endpoints', value['max'])
        self.assertEqual(value['max']['maximum_observed_logic_levels'], 16)
        self.assertEqual(value['max']['worst_sampled_path']['startpoint'], 'a/Q')

    def test_native_summary_metrics_and_missing_hold(self):
        text = '''
 | Design Timing Summary
 | ---------------------

    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints     WPWS(ns)
    -------      -------  ---------------------  -------------------      -------      -------  ---------------------  -------------------     --------
     -6.327   -81810.898                  49435               144664        0.056        0.000                      0               144664        2.283
'''
        value = results.timing_summary(text)
        self.assertEqual(value['max'], dict(wns_ns=-6.327, tns_ns=-81810.898,
                                            failing_endpoints=49435, endpoints=144664))
        self.assertEqual(value['min'], dict(wns_ns=0.056, tns_ns=0.0,
                                            failing_endpoints=0, endpoints=144664))
        missing = text.replace('        0.056        0.000                      0               144664',
                               '                                                                     ')
        self.assertTrue(all(v is None for v in results.timing_summary(missing)['min'].values()))
        self.assertTrue(all(v is None for v in results.timing_summary('missing')['max'].values()))

    def test_empty_sample_is_not_a_pass(self):
        report = self.work / 'endpoints.tsv'
        report.write_text('delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n')
        sample = results.endpoint_statistics(report)
        self.assertEqual(sample['max']['sampled_paths'], 0)
        self.assertIsNone(sample['max']['maximum_observed_logic_levels'])
        self.assertIsNone(sample['min']['worst_sampled_path'])

    def test_total_slice_lut_limit_includes_memory_and_exact_limit(self):
        manifest = self.work / 'manifest.json'
        manifest.write_text(json.dumps(dict(inputs=[], metadata={}, git={})))
        (self.work / 'soc_top_endpoints.tsv').write_text(
            'delay_type\tclock\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n')
        for count in (44999, 45000, 45001):
            with self.subTest(count=count):
                report = UTILIZATION.replace('58,210', str(count)).replace(
                    '56,075', str(count - 2135))
                (self.work / 'soc_top_utilization.rpt').write_text(report)
                value = results.summarize(manifest, self.work, 'synthesized')
                self.assertEqual(value['requirements']['slice_luts_maximum'], 45000)
                self.assertEqual(value['status']['slice_luts_within_limit'], count <= 45000)
                self.assertIsNone(value['status']['timing_150mhz_confirmed'])
        custom = results.summarize(manifest, self.work, 'synthesized', max_slice_luts=60000)
        self.assertTrue(custom['status']['slice_luts_within_limit'])
        self.assertEqual(custom['requirements']['slice_luts_maximum'], 60000)
        with self.assertRaises(ValueError):
            results.summarize(manifest, self.work, 'synthesized', max_slice_luts=0)

    def test_summary_does_not_derive_global_metrics_from_sample(self):
        manifest = self.work / 'manifest.json'
        manifest.write_text(json.dumps(dict(inputs=[], metadata={}, git={})))
        (self.work / 'soc_top_utilization.rpt').write_text(UTILIZATION)
        (self.work / 'soc_top_endpoints.tsv').write_text(
            'delay_type\tclock\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n'
            'max\tclk\ta\tx\t-1\t8\nmin\tclk\tb\ty\t0.1\t3\n')
        (self.work / 'soc_top_timing_summary.rpt').write_text('''
 | Design Timing Summary
    WNS(ns)      TNS(ns)  TNS Failing Endpoints  TNS Total Endpoints      WHS(ns)      THS(ns)  THS Failing Endpoints  THS Total Endpoints
    -------      -------  ---------------------  -------------------      -------      -------  ---------------------  -------------------
     -6.327   -81810.898                  49435               144664        0.056        0.000                      0               144664
''')
        value = results.summarize(manifest, self.work, 'synthesized')
        self.assertEqual(value['timing']['max']['tns_ns'], -81810.898)
        self.assertEqual(value['timing']['max']['endpoints'], 144664)
        self.assertEqual(value['timing']['max']['sample']['sampled_paths'], 1)
        self.assertIsNone(value['status']['all_connected_paths_within_limit'])

    def test_module_reports_select_distinct_endpoints_within_each_scope(self):
        runner = self.work / 'modules.tcl'
        runner.write_text('''
source [lindex $argv 0]
source [lindex $argv 1]
vivado_timing_mock::clear_paths
set ::cells [list soc/u_picorv32/pc soc/u_picorv32/state \
    soc/u_block_dma_arbiter/request soc/u_cpu_axi_write_pingpong/valid \
    soc/g_frame_schedule.u_scheduler/column soc/g_shared_ia_ps.g_channels.u_ram/fault]
proc get_cells {args} {
    set filter [vivado_timing_mock::option $args -filter]
    if {![regexp {^IS_SEQUENTIAL == 1 && NAME =~ (.*)$} $filter -> pattern]} {
        error "Expected a sequential-cell scope filter"
    }
    set selected {}
    foreach cell $::cells {
        if {[string match $pattern $cell]} { lappend selected $cell }
    }
    return $selected
}
foreach {name delay endpoint slack levels} {
    cpu_worst max soc/u_picorv32/pc/D -2.0 18
    cpu_same_endpoint max soc/u_picorv32/pc/D -1.5 17
    cpu_other_endpoint max soc/u_picorv32/state/D -1.0 12
    cpu_hold min soc/u_picorv32/pc/D 0.1 2
    dma_max max soc/u_block_dma_arbiter/request/D -0.5 11
    dma_min min soc/u_block_dma_arbiter/request/D 0.2 3
    axi_max max soc/u_cpu_axi_write_pingpong/valid/D -0.2 8
    scheduler_max max soc/g_frame_schedule.u_scheduler/column/D -0.1 7
    shared_max max soc/g_shared_ia_ps.g_channels.u_ram/fault/D -0.3 9
} {
    vivado_timing_mock::add_path $name $delay $endpoint $slack soc_clk soc_clk 6.667
    dict set ::vivado_timing_mock::paths $name LOGIC_LEVELS $levels
}
proc report_timing {args} {
    set name [vivado_timing_mock::option $args -of_objects]
    return "Slack (MET) : [get_property SLACK $name] ns\\n  Source: [get_property STARTPOINT_PIN $name]\\n  Destination: [get_property ENDPOINT_PIN $name]\\n"
}
soc_reports::write_module_paths [lindex $argv 2] fpga_top 2
''')
        process = subprocess.run([
            'tclsh', str(runner), str(ROOT / 'scripts/fpga/tests/vivado_timing_mock.tcl'),
            str(ROOT / 'scripts/fpga/vivado_soc_reports.tcl'), str(self.work),
        ], text=True, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        with (self.work / 'fpga_top_module_endpoints.tsv').open() as stream:
            rows = list(csv.DictReader(stream, delimiter='\t'))
        cpu = [row for row in rows if row['scope'] == 'cpu' and row['delay_type'] == 'max']
        self.assertEqual([row['endpoint'] for row in cpu],
                         ['soc/u_picorv32/pc/D', 'soc/u_picorv32/state/D'])
        self.assertEqual([row['slack_ns'] for row in cpu], ['-2.0', '-1.0'])
        self.assertEqual({row['scope'] for row in rows}, {'cpu', 'dma', 'axi', 'scheduler', 'shared_storage'})
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row['clock'] == 'soc_clk' for row in rows))
        self.assertEqual(next(row for row in rows if row['scope'] == 'axi')['endpoint'],
                         'soc/u_cpu_axi_write_pingpong/valid/D')
        report = (self.work / 'fpga_top_module_paths.rpt').read_text()
        self.assertIn('Scope: im2col; sequential cells: 0', report)
        self.assertIn('soc/u_block_dma_arbiter/request/D', report)

    def run_native_flow(self, *, routed=False, fail_route=False, board=False):
        mock = ROOT / 'scripts/fpga/tests/vivado_timing_mock.tcl'
        entry = ROOT / 'scripts/fpga' / ('vivado_synth_fpga.tcl' if board else 'vivado_synth_soc.tcl')
        output = self.work / 'reports with spaces'
        pin = self.work / 'soc_pins.xdc'
        pin.write_text('# Pin assignments are modeled by this test.\n')
        # Tcl 的 argv 通过 subprocess 传递，文件名不参与脚本字符串替换。
        runner = self.work / 'run.tcl'
        runner.write_text('''
set entry [lindex $argv 0]
set mock [lindex $argv 1]
set utilization [lindex $argv 2]
set routed_failure [lindex $argv 3]
set argv [lrange $argv 4 end]
source $mock
dict set ::vivado_timing_mock::paths setup_default LOGIC_LEVELS 9
dict set ::vivado_timing_mock::paths hold_default LOGIC_LEVELS 2
if {$routed_failure} { vivado_timing_mock::set_option fully_routed 0 }
proc version {args} { return command_model }
proc current_fileset {} { return sources_1 }
proc current_project {} { return project }
proc get_filesets {args} { return [lindex $args end] }
proc get_runs {args} { return [lindex $args end] }
proc get_files {args} { return [lindex $args end] }
proc get_ips {args} { return clk_wiz_0 }
proc vivado_timing_mock::prior_get_property {property object} {
    if {$property eq "STATUS"} { return Complete }
    if {$property eq "NAME"} { return $object }
    if {$property eq "IS_GENERATED"} { return [expr {$object eq "soc_clk"}] }
    if {$object eq "soc_clk"} {
        switch -- $property {
            SOURCE_PINS { return clocking/generator/CLKOUT2 }
            MASTER_CLOCK { return oscillator }
            MULTIPLY_BY { return 3 }
            DIVIDE_BY { return 1 }
        }
    }
    if {$object eq "clocking/generator"} {
        switch -- $property {
            REF_NAME { return MMCME2_ADV }
            CLKIN1_PERIOD { return 20.000 }
            CLKFBOUT_MULT_F { return 18.000 }
            DIVCLK_DIVIDE { return 1 }
            CLKOUT2_DIVIDE { return 6 }
        }
    }
    if {$property eq "REF_PIN_NAME"} { return [lindex [split $object /] end] }
    if {[string match "*ws_cell/mac" $object]} {
        switch -- $property {
            NAME { return $object }
            REF_NAME { return DSP48E1 }
            B_INPUT { return DIRECT }
            BREG - BCASCREG - AREG - ACASCREG { return 1 }
            MREG - PREG { return 0 }
        }
    }
    return ""
}
proc get_cells {args} {
    if {$args eq {-hierarchical -filter {REF_NAME == soc_top || ORIG_REF_NAME == soc_top}}} {
        return processor
    }
    if {$args eq {-hierarchical -filter {REF_NAME == MMCME2_ADV || REF_NAME == MMCME2_BASE}}} {
        return clocking/generator
    }
    set result [list]
    for {set row 0} {$row < 16} {incr row} {
        for {set column 0} {$column < 16} {incr column} {
            lappend result [format {u_soc_top/u_npu_axil_top/u_npu_top/u_compute_core/u_systolic_array/gen_row[%d].gen_col[%d].ws_cell/mac} $row $column]
        }
    }
    return $result
}
proc get_pins {args} {
    if {$args eq {-of_objects processor -filter {REF_PIN_NAME == clk}}} { return processor/clk }
    if {$args eq {-of_objects clocking/generator -filter {DIRECTION == OUT && REF_PIN_NAME =~ CLKOUT*}}} {
        return clocking/generator/CLKOUT2
    }
    if {$args eq {-of_objects clocking/generator -filter {REF_PIN_NAME == CLKIN1 || REF_PIN_NAME == CLKIN2}}} {
        return {clocking/generator/CLKIN1 clocking/generator/CLKIN2}
    }
    return [list]
}
rename get_clocks get_clocks_timing_model
proc get_clocks {args} {
    if {$args eq "oscillator" || $args eq {-of_objects clocking/generator/CLKIN1}} { return oscillator }
    if {$args eq {-of_objects clocking/generator/CLKIN2}} { return {} }
    return [get_clocks_timing_model {*}$args]
}
proc get_nets {args} { return {} }
proc all_fanin {args} {
    if {$args ne {-flat processor/clk}} { error "Unexpected clock fan-in query" }
    return {clocking/generator/CLKOUT2 clocking/buffer/I}
}
vivado_timing_mock::set_clock oscillator 20.000
foreach command {set_param create_project set_property read_verilog read_xdc synth_design opt_design place_design phys_opt_design route_design write_checkpoint} {
    proc $command {args} [format {vivado_timing_mock::record %s {*}$args; return} $command]
}
foreach command {add_files generate_target export_ip_user_files update_compile_order launch_runs wait_on_run open_run} {
    proc $command {args} [format {vivado_timing_mock::record %s {*}$args; return} $command]
}
foreach command {report_high_fanout_nets report_design_analysis} {
    proc $command {args} { vivado_timing_mock::report_file $args }
}
proc report_timing {args} {
    if {[lsearch -exact $args -return_string] >= 0} {
        set path [vivado_timing_mock::option $args -of_objects]
        return "Slack (MET) : 1.0ns\n  Source: $path\n  Destination: $path\n"
    }
    vivado_timing_mock::report_file $args
}
proc report_utilization {args} {
    set destination [vivado_timing_mock::option $args -file]
    file copy -force $::utilization $destination
}
source $entry
''')
        utilization = self.work / 'utilization.rpt'
        utilization.write_text(UTILIZATION)
        arguments = ['tclsh', str(runner), str(entry), str(mock), str(utilization),
                     str(int(fail_route)), str(output)]
        if routed and not board:
            arguments.append(str(pin))
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('NPU_', 'GEMPACT_', 'VIVADO_', 'SHARED_', 'IM2COL_'))}
        environment['NPU_CONFIG'] = str(ROOT / 'config/npu_fpga.mk')
        if board and routed:
            environment['VIVADO_RUN_IMPL'] = '1'
        process = subprocess.run(arguments, cwd=ROOT, env=environment,
                                 text=True, capture_output=True, timeout=60)
        # 本模型使用 58,210 个 Slice LUT；实现目标检查必须以非零状态结束。
        self.assertEqual(process.returncode == 0, not routed, process.stdout + process.stderr)
        if board:
            output = output / 'reports'
        directory = output / 'routed' if routed else output
        return json.loads((directory / 'measurement.json').read_text()), output

    def test_native_synthesis_metadata_and_result(self):
        value, output = self.run_native_flow()
        self.assertFalse(value['status']['slice_luts_within_limit'])
        self.assertIsNone(value['status']['timing_150mhz_confirmed'])
        self.assertIsNone(value['status']['all_connected_paths_within_limit'])
        self.assertFalse(value['status']['connectivity_complete'])
        self.assertEqual(value['timing']['max']['tns_ns'], 0)
        self.assertGreater(value['timing']['max']['sample']['sampled_paths'], 0)
        self.assertIn('完整连通图', value['logic_level_scope'])
        self.assertEqual(value['configuration']['vivado_version'], 'command_model')
        manifest = json.loads((output / 'source_manifest.json').read_text())
        names = [row['relative_path'] for row in manifest['inputs']]
        self.assertIn('rtl/common/regfile.v', names)
        self.assertIn('rtl/npu/compute/compute_core.sv', names)
        self.assertGreater(len(names), 75)
        self.assertIn('test/pe_dsp_boundary/check.py', names)
        dsp = json.loads((output / 'pe_dsp_boundary/dsp_b_cascade.json').read_text())
        self.assertTrue(dsp['passed'])
        self.assertEqual(dsp['pe_count'], 256)

    def test_native_routing_status(self):
        value, _ = self.run_native_flow(routed=True)
        self.assertTrue(value['status']['timing_150mhz_confirmed'])
        self.assertFalse(value['status']['slice_luts_within_limit'])
        self.assertFalse(value['status']['all_targets_met'])

    def test_failed_routing_still_records_measured_values(self):
        value, _ = self.run_native_flow(routed=True, fail_route=True)
        self.assertFalse(value['status']['timing_150mhz_confirmed'])
        self.assertEqual(value['resources']['slice_luts'], 58210)

    def test_board_top_measurement(self):
        value, output = self.run_native_flow(board=True)
        self.assertEqual(value['configuration']['top'], 'fpga_top')
        self.assertEqual(value['configuration']['core_clock_mhz'], '150.000')
        self.assertEqual(value['configuration']['synthesis_directive'], 'PerformanceOptimized')
        self.assertTrue((output / 'fpga_top_endpoints.tsv').exists())
        self.assertTrue((output / 'fpga_top_module_endpoints.tsv').exists())
        self.assertTrue((output / 'fpga_top_module_paths.rpt').exists())
        self.assertTrue((output / 'fpga_top_logic_levels.rpt').exists())
        self.assertTrue((output / 'pe_dsp_boundary/dsp_b_cascade.json').exists())
        self.assertIsNone(value['status']['timing_150mhz_confirmed'])

    def test_board_top_routing(self):
        value, _ = self.run_native_flow(board=True, routed=True)
        self.assertTrue(value['status']['timing_150mhz_confirmed'])

    def test_board_top_failed_routing(self):
        value, _ = self.run_native_flow(board=True, routed=True, fail_route=True)
        self.assertFalse(value['status']['timing_150mhz_confirmed'])


if __name__ == '__main__':
    unittest.main()
