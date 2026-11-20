#!/usr/bin/env python3
"""用人工构造的报告和 Tcl 命令模型检查原生 Vivado 测量流程。"""
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

    def test_endpoint_statistics_cover_all_rows(self):
        report = self.work / 'endpoints.tsv'
        report.write_text('delay_type\tclock\tclock_period_ns\tstartpoint\tendpoint\tslack_ns\tlogic_levels\n'
                          'max\tclk\t6.667\ta/Q\tx/D\t-4.536\t16\n'
                          'max\tclk\t6.667\tb/Q\tx/D\t-1.0\t9\n'
                          'max\tclk\t6.667\tc/Q\ty/D\t-2.0\t12\n'
                          'max\tclk\t6.667\td/Q\tz/D\t0.5\t8\n'
                          'min\tclk\t6.667\te/Q\tz/D\t0.1\t2\n')
        value = results.endpoint_statistics(report)
        self.assertEqual(value['max']['endpoints'], 3)
        self.assertEqual(value['max']['failing_endpoints'], 2)
        self.assertAlmostEqual(value['max']['tns_ns'], -6.536)
        self.assertEqual(value['max']['maximum_observed_logic_levels'], 16)

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
    set result [list]
    for {set row 0} {$row < 16} {incr row} {
        for {set column 0} {$column < 16} {incr column} {
            lappend result [format {u_soc_top/u_npu_axil_top/u_npu_top/u_compute_core/u_systolic_array/gen_row[%d].gen_col[%d].ws_cell/mac} $row $column]
        }
    }
    return $result
}
proc get_pins {args} { return [list] }
foreach command {set_param create_project set_property read_verilog read_xdc synth_design opt_design place_design phys_opt_design route_design write_checkpoint} {
    proc $command {args} [format {vivado_timing_mock::record %s {*}$args; return} $command]
}
foreach command {add_files generate_target export_ip_user_files update_compile_order launch_runs wait_on_run open_run} {
    proc $command {args} [format {vivado_timing_mock::record %s {*}$args; return} $command]
}
foreach command {report_timing_summary report_timing report_high_fanout_nets} {
    proc $command {args} { vivado_timing_mock::report_file $args }
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
        self.assertEqual(process.returncode == 0, not fail_route, process.stdout + process.stderr)
        if board:
            output = output / 'reports'
        directory = output / 'routed' if routed else output
        return json.loads((directory / 'measurement.json').read_text()), output

    def test_native_synthesis_metadata_and_result(self):
        value, output = self.run_native_flow()
        self.assertFalse(value['status']['slice_luts_within_limit'])
        self.assertIsNone(value['status']['timing_150mhz_confirmed'])
        self.assertTrue(value['status']['observed_endpoint_paths_within_nine_levels'])
        self.assertIsNone(value['status']['all_connected_paths_within_nine_levels'])
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
