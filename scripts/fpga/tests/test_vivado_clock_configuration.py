#!/usr/bin/env python3
"""检查精确时钟配置、报告舍入和实际输出引脚选择；不执行 Vivado。"""
import csv
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('vivado_clock_results', ROOT / 'scripts/fpga/vivado_soc_results.py')
results = importlib.util.module_from_spec(spec)
spec.loader.exec_module(results)


def native_clock(**changes):
    value = dict(clock='core', period_ns='6.667', object='clk', clock_kind='primary',
                 definition_frequency_mhz='150.0', definition_period_ns='6.666666666666667',
                 source_pin='clk', soc_clock_pin='clk', same_source='1')
    value.update(changes)
    return value


def mmcm_clock(**changes):
    value = dict(clock='core', period_ns='6.667', object='clocking/generator/CLKOUT2',
                 clock_kind='mmcm', source_pin='clocking/generator/CLKOUT2',
                 source_cell='clocking/generator', source_ref='MMCME2_ADV',
                 soc_clock_pin='tiles/processor/clk', same_source='1', master_clock='oscillator',
                 master_period_ns='20.000', master_is_generated='0', multiply_by='3', divide_by='1',
                 mmcm_input_period_ns='20.000', mmcm_feedback_multiplier='18.000',
                 mmcm_input_divider='1', mmcm_output_divider='6')
    value.update(changes)
    return value


CLOCK_MODEL = r'''
set ::soc_instances {tiles/processor}
set ::mmcm_instances {clocking/generator}
set ::clock_fanin {clocking/generator/CLKOUT2 clocking/buffer/I clocking/buffer/O}
set ::clock_properties [dict create \
    core [dict create PERIOD 6.667 IS_GENERATED 1 SOURCE_PINS {clocking/generator/CLKOUT2} \
        MASTER_CLOCK oscillator MULTIPLY_BY 3 DIVIDE_BY 1] \
    oscillator [dict create PERIOD 20.000 IS_GENERATED 0] \
    clk [dict create REF_PIN_NAME clk] \
    tiles/processor/clk [dict create REF_PIN_NAME clk] \
    clocking/generator [dict create REF_NAME MMCME2_ADV CLKIN1_PERIOD 20.000 \
        CLKFBOUT_MULT_F 18.000 DIVCLK_DIVIDE 1 CLKOUT2_DIVIDE 6] \
    clocking/generator/CLKOUT2 [dict create REF_PIN_NAME CLKOUT2] \
    clocking/generator/CLKIN1 [dict create REF_PIN_NAME CLKIN1] \
    clocking/generator/CLKIN2 [dict create REF_PIN_NAME CLKIN2]]
set ::clocks_on [dict create clk core tiles/processor/clk core \
    clocking/generator/CLKOUT2 core clocking/generator/CLKIN1 oscillator \
    clocking/generator/CLKIN2 {}]
set ::clock_nets [dict create]
proc get_property {property objects} {
    if {$property eq "NAME"} { return $objects }
    if {[dict exists $::clock_properties $objects $property]} {
        return [dict get $::clock_properties $objects $property]
    }
    return ""
}
proc get_cells {args} {
    if {$args eq {-hierarchical -filter {REF_NAME == soc_top || ORIG_REF_NAME == soc_top}}} {
        return $::soc_instances
    }
    if {$args eq {-hierarchical -filter {REF_NAME == MMCME2_ADV || REF_NAME == MMCME2_BASE}}} {
        return $::mmcm_instances
    }
    error "Unexpected cell query: $args"
}
proc get_pins {args} {
    if {[lrange $args 0 0] ne {-of_objects}} { error "A clock pin must come from an object query" }
    set object [lindex $args 1]
    set filter [lindex $args 3]
    if {$object in $::soc_instances && $filter eq {REF_PIN_NAME == clk}} { return ${object}/clk }
    if {$object in $::mmcm_instances && $filter eq {DIRECTION == OUT && REF_PIN_NAME =~ CLKOUT*}} {
        return ${object}/CLKOUT2
    }
    if {$object in $::mmcm_instances && $filter eq {REF_PIN_NAME == CLKIN1 || REF_PIN_NAME == CLKIN2}} {
        return [list ${object}/CLKIN1 ${object}/CLKIN2]
    }
    error "Unexpected pin query: $args"
}
proc get_ports {args} {
    if {$args ne "clk"} { error "Unexpected clock port query" }
    return clk
}
proc get_nets {args} {
    if {[lrange $args 0 1] ne {-segments -of_objects}} { error "Unexpected clock net query" }
    set object [lindex $args 2]
    if {[dict exists $::clock_nets $object]} { return [dict get $::clock_nets $object] }
    return {}
}
proc get_clocks {args} {
    if {[lindex $args 0] eq "-of_objects"} {
        set object [lindex $args 1]
        if {[dict exists $::clocks_on $object]} { return [dict get $::clocks_on $object] }
        return {}
    }
    if {$args eq "oscillator"} { return oscillator }
    return {}
}
proc all_fanin {args} {
    if {[llength $args] != 2 || [lindex $args 0] ne "-flat" ||
        [lindex $args 1] ne "tiles/processor/clk"} { error "Unexpected fan-in traversal" }
    return $::clock_fanin
}
proc create_clock {args} {
    if {[lrange $args 0 1] ne {-name clk} || [lindex $args 2] ne "-period" ||
        [lindex $args 4] ne "clk"} { error "Unexpected primary clock definition" }
    set ::applied_period [lindex $args 3]
    dict set ::clock_properties core IS_GENERATED 0
}
'''


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='vivado_clock_')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)

    def check_rows(self, *rows):
        path = self.work / 'core_clock.tsv'
        fields = sorted(set().union(*(row.keys() for row in rows)))
        with path.open('w') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, delimiter='\t')
            writer.writeheader()
            writer.writerows(rows)
        return results.core_clock(path)

    def test_native_exact_frequency_accepts_picosecond_display(self):
        for period in ('6.667', '6.666666666666667'):
            value = self.check_rows(native_clock(period_ns=period))
            self.assertTrue(value['within_150mhz_period'])
            self.assertEqual(value['configured_frequency_mhz'], 150.0)
            self.assertEqual(value['frequency_basis'], 'applied_create_clock')

    def test_reported_period_does_not_supply_precise_configuration(self):
        for period, expected in (('6.667', None), ('6.666', True), ('6.668', False)):
            value = self.check_rows(dict(clock='core', period_ns=period, object='clk'))
            self.assertIs(value['within_150mhz_period'], expected)
        self.assertIsNone(self.check_rows(native_clock(definition_period_ns='6.667'))['within_150mhz_period'])
        actual = native_clock(definition_frequency_mhz='149.99250037498125', definition_period_ns='6.667')
        self.assertFalse(self.check_rows(actual)['within_150mhz_period'])

    def test_mmcm_frequency_uses_exact_hardware_ratio(self):
        value = self.check_rows(mmcm_clock())
        self.assertTrue(value['within_150mhz_period'])
        self.assertEqual(value['configured_frequency_mhz'], 150.0)
        self.assertEqual(value['frequency_basis'], 'mmcm_configuration')
        slower = mmcm_clock(period_ns='10.000', multiply_by='2', mmcm_feedback_multiplier='12')
        self.assertFalse(self.check_rows(slower)['within_150mhz_period'])

    def test_mmcm_missing_or_inconsistent_configuration_is_unconfirmed(self):
        variants = [dict(multiply_by='4'), dict(master_period_ns='25.000'), dict(period_ns='6.666'),
                    dict(same_source='0'), dict(source_ref='UNKNOWN'), dict(source_cell=''),
                    dict(master_is_generated='1'), dict(mmcm_input_divider='NaN')]
        variants += [{key: ''} for key in ('mmcm_input_period_ns', 'mmcm_feedback_multiplier',
                                          'mmcm_input_divider', 'mmcm_output_divider',
                                          'master_clock', 'multiply_by', 'divide_by')]
        for change in variants:
            with self.subTest(change=change):
                self.assertIsNone(self.check_rows(mmcm_clock(**change))['within_150mhz_period'])
        self.assertIsNone(self.check_rows(mmcm_clock(), mmcm_clock(clock='other'))['within_150mhz_period'])
        self.assertIsNone(self.check_rows(native_clock(definition_frequency_mhz=''))['within_150mhz_period'])

    def tcl_clock(self, name, configuration='', *, native=False, accepted=True):
        folder = self.work / name
        folder.mkdir()
        script = folder / 'run.tcl'
        script.write_text('source [lindex $argv 0]\n' + CLOCK_MODEL + '\n' + configuration + '\n' +
                          ('soc_reports::define_core_clock 150.0\n' if native else '') +
                          'soc_reports::write_core_clock [lindex $argv 1] ' +
                          ('soc_top' if native else 'fpga_top') + '\n')
        process = subprocess.run(['tclsh', str(script), str(ROOT / 'scripts/fpga/vivado_soc_reports.tcl'),
                                  str(folder)], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode == 0, accepted, process.stdout + process.stderr)
        return results.core_clock(folder / ('soc_top_core_clock.tsv' if native else 'fpga_top_core_clock.tsv'))

    def test_tcl_queries_actual_mmcm_output_and_propagated_soc_clock(self):
        self.assertTrue(self.tcl_clock('renamed_hierarchy')['within_150mhz_period'])
        fallback = '''dict set ::clocks_on tiles/processor/clk {}
dict set ::clock_nets tiles/processor/clk {clocking/soc_net}
dict set ::clocks_on clocking/soc_net core'''
        self.assertTrue(self.tcl_clock('net_propagation', fallback)['within_150mhz_period'])
        native = self.tcl_clock('primary_definition', native=True)
        self.assertTrue(native['within_150mhz_period'])
        self.assertEqual(native['configuration']['definition_period_ns'], '6.666666666666667')

    def test_tcl_ambiguous_sources_and_missing_parameters_are_unconfirmed(self):
        errors = {
            'two_soc': 'set ::soc_instances {tiles/processor tiles/secondary}',
            'two_mmcm': 'lappend ::mmcm_instances clocking/other; lappend ::clock_fanin clocking/other/CLKOUT2',
            'two_output_clocks': 'dict set ::clocks_on clocking/generator/CLKOUT2 {core other}',
            'different_soc_clock': 'dict set ::clocks_on tiles/processor/clk other',
            'different_source': 'dict set ::clock_properties core SOURCE_PINS clocking/other/CLKOUT2',
            'missing_source': 'set ::clock_fanin {}',
        }
        for name, code in errors.items():
            with self.subTest(name=name):
                self.assertIsNone(self.tcl_clock(name, code, accepted=False)['within_150mhz_period'])
        for name, code in {
            'missing_parameter': 'dict unset ::clock_properties clocking/generator DIVCLK_DIVIDE',
            'ratio_mismatch': 'dict set ::clock_properties core MULTIPLY_BY 4',
        }.items():
            with self.subTest(name=name):
                self.assertIsNone(self.tcl_clock(name, code)['within_150mhz_period'])


if __name__ == '__main__':
    unittest.main()
