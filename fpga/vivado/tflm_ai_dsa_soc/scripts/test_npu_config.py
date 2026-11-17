#!/usr/bin/env python3
"""Check literal FPGA configuration and Vivado Tcl parameter propagation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENVIRONMENT_KEYS = (
    'NPU_CONFIG', 'NPU_AXI_DATA_WIDTH', 'SHARED_BANK_BYTES', 'SHARED_BANK_COUNT',
    'GEMPACT_PCR_ENGINE', 'GEMPACT_PS_COMPRESS', 'GEMPACT_PS_POOL_BYTES', 'GEMPACT_PS_FORCE_RAW',
    'VIVADO_SYNTH_STRATEGY', 'VIVADO_SYNTH_DIRECTIVE', 'VIVADO_IMPL_STRATEGY', 'VIVADO_RUN_IMPL',
    'VIVADO_CPU_ENABLE_ICACHE', 'VIVADO_CPU_MEM_PATH', 'VIVADO_SIM_MAX_SYS_CYCLES',
    'VIVADO_NPU_ENABLE_IS_MODE', 'VIVADO_NPU_ENABLE_PER_CHANNEL', 'VIVADO_NPU_WEIGHT_WIDTH',
    'VIVADO_NPU_DATA_WIDTH', 'VIVADO_NPU_ADDR_WIDTH', 'VIVADO_NPU_ENABLE_CLOCK_GATING',
)
HELPER_RUNNER = r'''
source [lindex $argv 0]
set values [npu_config::read [lindex $argv 1]]
foreach name {NPU_AXI_DATA_WIDTH SHARED_BANK_BYTES SHARED_BANK_COUNT PCR_ENGINE PS_POOL_BYTES PS_FORCE_RAW} {
    puts "VALUE\t$name\t[dict get $values $name]"
}
puts "PATH\t[dict get $values config_path]"
'''
VIVADO_RUNNER = r'''
set entry [lindex $argv 0]
set argv [lrange $argv 1 end]
set properties [dict create]
if {[info exists ::env(TEST_SOURCE_GENERICS)]} {
    dict set properties sources_1 generic $::env(TEST_SOURCE_GENERICS)
    dict set properties sim_1 generic $::env(TEST_SOURCE_GENERICS)
}
proc set_property {args} {
    if {[llength $args] == 3 && [lindex $args 0] ne "-dict"} {
        lassign $args property value object
        dict set ::properties $object $property $value
        if {$property eq "generic" && $object eq "sim_1" && [info exists ::env(TEST_STOP_AT_SIM_GENERIC)]} {
            return -code error TEST_PARAMETERS_CAPTURED
        }
    }
}
proc get_property {property object} {
    if {$property eq "STATUS"} { return "Complete" }
    if {[dict exists $::properties $object $property]} {
        return [dict get $::properties $object $property]
    }
    return ""
}
proc current_project {} { return project }
proc get_filesets {args} { return [lindex $args end] }
proc get_runs {args} { return [lindex $args end] }
proc get_ips {args} { return clk_wiz_0 }
proc get_files {args} { return {} }
proc create_project {args} {
    set offset [expr {[lindex $args 0] eq "-force" ? 1 : 0}]
    set name [lindex $args $offset]
    set path [lindex $args [expr {$offset+1}]]
    file mkdir $path
    close [open [file join $path "$name.xpr"] w]
}
foreach command {
    set_param add_files generate_target export_ip_user_files update_compile_order
    launch_runs wait_on_run open_run open_project report_utilization report_timing_summary
    report_timing report_high_fanout_nets report_route_status report_drc report_power
    write_checkpoint write_bitstream
} {
    proc $command {args} { return }
}
set status [catch {source $entry} message options]
if {$status && $message ne "TEST_PARAMETERS_CAPTURED"} {
    puts stderr [dict get $options -errorinfo]
    exit 1
}
dict for {object values} $properties {
    if {[dict exists $values generic]} {
        foreach item [dict get $values generic] {
            set equal [string first = $item]
            puts "GENERIC\t$object\t[string range $item 0 [expr {$equal-1}]]\t[string range $item [expr {$equal+1}] end]"
        }
    }
    if {[dict exists $values verilog_define]} {
        puts "DEFINES\t$object\t[dict get $values verilog_define]"
    }
}
puts TCL_PARAMETERS_PASS
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConfigurationTests(unittest.TestCase):
    directory: Path
    tclsh: str
    picorv32: Path | None
    cases = []

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=self._testMethodName+'_', dir=self.directory)
        self.work = Path(self.temporary.name)
        self.config = self.work/'selected hardware.mk'
        self.config.write_text('')
        self.environment = {key: value for key, value in os.environ.items()
                            if key not in ENVIRONMENT_KEYS and not key.startswith('TEST_')}
        self.environment['NPU_CONFIG'] = str(self.config)
        if self.picorv32:
            self.environment['PICORV32_ROOT'] = str(self.picorv32)
        self.helper = self.work/'read_config.tcl'
        self.helper.write_text(HELPER_RUNNER)
        self.vivado = self.work/'vivado_commands.tcl'
        self.vivado.write_text(VIVADO_RUNNER)
        self.memory = self.work/'cpu.mem'
        self.memory.write_text('11223344\n55667788\n99aabbcc\nddeeff00\n')

    def tearDown(self):
        self.temporary.cleanup()

    def execute(self, command, *, environment=None, success=True):
        result = subprocess.run([self.tclsh, *map(str, command)], cwd=ROOT,
                                env=environment or self.environment, text=True, capture_output=True, timeout=60)
        if success:
            self.assertEqual(result.returncode, 0, result.stdout+'\n'+result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        self.cases.append(dict(test=self._testMethodName, accepted=result.returncode==0,
                               expected_accept=success))
        return result

    def read_values(self, *, success=True, environment=None):
        result = self.execute([self.helper, HERE/'npu_config.tcl', ROOT], success=success,
                              environment=environment)
        values = {}
        for line in result.stdout.splitlines():
            if line.startswith('VALUE\t'):
                _, key, value = line.split('\t')
                values[key] = int(value)
        return values, result

    def flow(self, name, output, *, script_dir=HERE, environment=None, memory=None):
        arguments = [output, 'xc7a200tfbg484-3', 16, 4, 16]
        if name == 'export_project.tcl':
            arguments.append(memory or self.memory)
        else:
            arguments += [1, memory or self.memory]
        result = self.execute([self.vivado, script_dir/name, *arguments], environment=environment)
        self.assertIn('TCL_PARAMETERS_PASS', result.stdout)
        generics, defines = {}, {}
        for line in result.stdout.splitlines():
            if line.startswith('GENERIC\t'):
                _, fileset, key, value = line.split('\t', 3)
                generics.setdefault(fileset, {})[key] = value
            if line.startswith('DEFINES\t'):
                _, fileset, value = line.split('\t', 2)
                defines[fileset] = value.split()
        return generics, defines

    def test_default_values(self):
        values, result = self.read_values()
        self.assertEqual(values, dict(NPU_AXI_DATA_WIDTH=64, SHARED_BANK_BYTES=8192,
                                     SHARED_BANK_COUNT=7, PCR_ENGINE=1, PS_POOL_BYTES=49152, PS_FORCE_RAW=0))
        self.assertIn(str(self.config), result.stdout)

    def test_default_fpga_configuration_file(self):
        environment = {key: value for key, value in self.environment.items() if key != 'NPU_CONFIG'}
        values, result = self.read_values(environment=environment)
        self.assertEqual(values['SHARED_BANK_BYTES'], 8192)
        self.assertEqual(values['SHARED_BANK_COUNT'], 7)
        self.assertEqual(values['PS_POOL_BYTES'], 49152)
        self.assertIn(str(ROOT/'config/npu_fpga.mk'), result.stdout)

    def test_literal_syntax_and_unrelated_assignments(self):
        self.config.write_text('''# Hardware settings
export NPU_AXI_DATA_WIDTH ?= +032 # decimal
SHARED_BANK_BYTES := 0x2000
SHARED_BANK_COUNT = 09
PCR_ENGINE = 1
PS_POOL_BYTES := 0x6000
PS_FORCE_RAW = 1
UNRELATED = $(shell echo unused)
''')
        values, _ = self.read_values()
        self.assertEqual((values['NPU_AXI_DATA_WIDTH'], values['SHARED_BANK_BYTES'],
                          values['SHARED_BANK_COUNT'], values['PS_POOL_BYTES']), (32, 8192, 9, 24576))

    def test_all_supported_geometries(self):
        for bus in (32, 64):
            for size in (8192,):
                for count in (6, 7, 8, 9):
                    with self.subTest(bus=bus, size=size, count=count):
                        self.config.write_text(f'NPU_AXI_DATA_WIDTH={bus}\nSHARED_BANK_BYTES={size}\nSHARED_BANK_COUNT={count}\n')
                        values, _ = self.read_values()
                        self.assertEqual([values[key] for key in ('NPU_AXI_DATA_WIDTH', 'SHARED_BANK_BYTES', 'SHARED_BANK_COUNT')],
                                         [bus, size, count])

    def test_environment_overrides(self):
        self.config.write_text('NPU_AXI_DATA_WIDTH=32\nSHARED_BANK_BYTES=2048\nSHARED_BANK_COUNT=6\n')
        self.environment.update(NPU_AXI_DATA_WIDTH='64', SHARED_BANK_BYTES='8192', SHARED_BANK_COUNT='9')
        values, _ = self.read_values()
        self.assertEqual([values[key] for key in ('NPU_AXI_DATA_WIDTH', 'SHARED_BANK_BYTES', 'SHARED_BANK_COUNT')], [64, 8192, 9])

    def test_invalid_values(self):
        for key, value in (('NPU_AXI_DATA_WIDTH', '16'), ('NPU_AXI_DATA_WIDTH', '128'),
                           ('SHARED_BANK_BYTES', '512'), ('SHARED_BANK_BYTES', '1536'),
                           ('SHARED_BANK_BYTES', '1024'), ('SHARED_BANK_BYTES', '2048'),
                           ('SHARED_BANK_BYTES', '4096'), ('SHARED_BANK_BYTES', '16384'),
                           ('SHARED_BANK_COUNT', '5'),
                           ('SHARED_BANK_COUNT', '10'), ('SHARED_BANK_COUNT', '-1'),
                           ('PCR_ENGINE', '2'), ('PS_FORCE_RAW', '2'), ('PS_POOL_BYTES', '65')):
            with self.subTest(key=key, value=value):
                self.config.write_text(f'{key}={value}\n')
                _, result = self.read_values(success=False)
                self.assertIn(key, result.stderr)
        self.config.write_text('')
        for value in ('2048', '4096'):
            self.environment['SHARED_BANK_BYTES'] = value
            _, result = self.read_values(success=False)
            self.assertIn('SHARED_BANK_BYTES=8192', result.stderr)
        self.environment.pop('SHARED_BANK_BYTES')
        self.environment['NPU_AXI_DATA_WIDTH'] = ''
        self.read_values(success=False)

    def test_rejected_make_expressions_and_duplicates(self):
        sentinel = self.work/'evaluated'
        for text in ('NPU_AXI_DATA_WIDTH=$(BUS)\n', 'NPU_AXI_DATA_WIDTH+=64\n',
                     'NPU_AXI_DATA_WIDTH=32\nNPU_AXI_DATA_WIDTH=64\n',
                     f'NPU_AXI_DATA_WIDTH=[exec touch {sentinel}]\n'):
            with self.subTest(text=text):
                self.config.write_text(text)
                self.read_values(success=False)
                self.assertFalse(sentinel.exists())

    def test_missing_configuration(self):
        self.config.unlink()
        self.read_values(success=False)

    def test_four_build_entries(self):
        for bus, size, count in ((64, 8192, 7), (32, 8192, 9)):
            self.config.write_text(f'NPU_AXI_DATA_WIDTH={bus}\nSHARED_BANK_BYTES={size}\nSHARED_BANK_COUNT={count}\n')
            for name in ('create_project.tcl', 'run_batch_synth.tcl', 'run_batch_impl.tcl', 'export_project.tcl'):
                with self.subTest(bus=bus, name=name):
                    generics, defines = self.flow(name, self.work/(name+str(bus)))
                    expected = dict(BUS_WIDTH=str(bus), SHARED_BANK_BYTES=str(size), SHARED_BANK_COUNT=str(count),
                                    SIZE='16', IA_CACHE_BLOCKS='4', CPU_MEM_DP='16')
                    self.assertEqual({key: generics['sources_1'][key] for key in expected}, expected)
                    self.assertIn('GEMPACT_PS_COMPRESS', defines['sources_1'])
                    image = Path(generics['sources_1']['CPU_MEM_PATH'].strip('"'))
                    cpu_words = self.memory.read_text().splitlines() + ['00000000'] * 12
                    expected_words = cpu_words if bus == 32 else [
                        cpu_words[i+1] + cpu_words[i] for i in range(0, 16, 2)]
                    self.assertEqual(image.read_text().splitlines(), expected_words)
                    self.assertEqual((image.parent/'cpu32.mem').read_text().splitlines(), cpu_words)
                    if name == 'export_project.tcl':
                        self.assertEqual({key: generics['sim_1'][key] for key in expected}, expected)

    def test_build_entries_require_complete_bram_data_capacity(self):
        for size in (2048, 4096):
            self.config.write_text(f'SHARED_BANK_BYTES={size}\n')
            for name in ('create_project.tcl', 'run_batch_synth.tcl', 'run_batch_impl.tcl', 'export_project.tcl'):
                with self.subTest(size=size, name=name):
                    output = self.work/(name+str(size))
                    arguments = [output, 'xc7a200tfbg484-3', 16, 4, 16]
                    arguments += [self.memory] if name == 'export_project.tcl' else [1, self.memory]
                    result = self.execute([self.vivado, HERE/name, *arguments], success=False)
                    self.assertIn('SHARED_BANK_BYTES=8192', result.stderr)
                    self.assertFalse(output.exists())

    def test_legacy_environment_overrides(self):
        self.config.write_text('PCR_ENGINE=0\nPS_POOL_BYTES=12288\nPS_FORCE_RAW=0\n')
        self.environment.update(GEMPACT_PCR_ENGINE='1', GEMPACT_PS_POOL_BYTES='24576', GEMPACT_PS_FORCE_RAW='1')
        _, defines = self.flow('create_project.tcl', self.work/'enabled')
        self.assertIn('GEMPACT_PS_COMPRESS', defines['sources_1'])
        self.assertIn('GEMMORA_PS_POOL_BYTES=24576', defines['sources_1'])
        self.assertIn('GEMMORA_PS_FORCE_RAW', defines['sources_1'])
        self.environment['GEMPACT_PS_COMPRESS'] = '0'
        _, defines = self.flow('create_project.tcl', self.work/'disabled')
        self.assertNotIn('GEMPACT_PS_COMPRESS', defines['sources_1'])

    def test_exported_scripts_and_configuration(self):
        self.config.write_text('NPU_AXI_DATA_WIDTH=32\nSHARED_BANK_BYTES=2048\nSHARED_BANK_COUNT=6\n')
        self.environment.update(NPU_AXI_DATA_WIDTH='64', SHARED_BANK_BYTES='8192', SHARED_BANK_COUNT='9',
                                GEMPACT_PS_FORCE_RAW='1')
        original = self.work/'export'
        self.flow('export_project.tcl', original)
        self.assertTrue((original/'scripts/npu_config.tcl').is_file())
        self.assertTrue((original/'scripts/cpu_memory.tcl').is_file())
        self.assertTrue((original/'scripts/export_sources.tcl').is_file())
        snapshot = (original/'config/npu_fpga.mk').read_text()
        self.assertIn('SHARED_BANK_BYTES := 8192', snapshot)
        self.assertIn('SHARED_BANK_COUNT := 9', snapshot)
        self.assertIn('PS_POOL_BYTES := 49152', snapshot)
        readme = (original/'README.md').read_text()
        self.assertIn('73728 bytes in 18 RAMB36E1', readme)
        self.assertIn('9216 parity bytes', readme)
        memory_words = (original/'mem/cpu32.mem').read_text().splitlines()
        self.assertEqual(memory_words[:4], self.memory.read_text().splitlines())
        self.assertEqual(memory_words[4:], ['00000000'] * 12)
        self.assertEqual((original/'mem/cpu.mem').read_text().splitlines(),
                         ['5566778811223344', 'ddeeff0099aabbcc'] + ['0000000000000000'] * 6)
        relocated = self.work/'relocated project'
        shutil.move(original, relocated)
        environment = {key: value for key, value in self.environment.items() if key not in ENVIRONMENT_KEYS}
        generics, defines = self.flow('create_project.tcl', relocated/'new project',
                                     script_dir=relocated/'scripts', environment=environment,
                                     memory=relocated/'mem/cpu32.mem')
        self.assertEqual(generics['sources_1']['BUS_WIDTH'], '64')
        self.assertEqual(generics['sources_1']['SHARED_BANK_BYTES'], '8192')
        self.assertEqual(generics['sources_1']['SHARED_BANK_COUNT'], '9')
        self.assertIn('GEMMORA_PS_FORCE_RAW', defines['sources_1'])
        for name in ('run_behav_smoke.tcl', 'run_post_impl_smoke.tcl'):
            environment.update(TEST_STOP_AT_SIM_GENERIC='1',
                TEST_SOURCE_GENERICS='BUS_WIDTH=64 SHARED_BANK_BYTES=8192 SHARED_BANK_COUNT=9 CPU_MEM_DP=16')
            result = self.execute([self.vivado, relocated/'scripts'/name,
                                   relocated/'project/tflm_ai_dsa_soc.xpr'], environment=environment)
            self.assertIn('GENERIC\tsim_1\tBUS_WIDTH\t64', result.stdout)
            self.assertIn('GENERIC\tsim_1\tSHARED_BANK_BYTES\t8192', result.stdout)
            self.assertIn('GENERIC\tsim_1\tSHARED_BANK_COUNT\t9', result.stdout)

    def test_existing_project_geometry_is_validated(self):
        exported = self.work/'export'
        self.flow('export_project.tcl', exported)
        for source_generics, error in (
                ('BUS_WIDTH=64 SHARED_BANK_BYTES=2048 SHARED_BANK_COUNT=7', 'SHARED_BANK_BYTES=8192'),
                ('BUS_WIDTH=32 SHARED_BANK_BYTES=4096 SHARED_BANK_COUNT=9', 'SHARED_BANK_BYTES=8192'),
                ('BUS_WIDTH=64 SHARED_BANK_BYTES=8192 SHARED_BANK_COUNT=10', 'SHARED_BANK_COUNT'),
                ('BUS_WIDTH=64 SHARED_BANK_COUNT=7', 'explicitly specify SHARED_BANK_BYTES')):
            environment = dict(self.environment, TEST_SOURCE_GENERICS=source_generics,
                               TEST_STOP_AT_SIM_GENERIC='1')
            for name in ('run_behav_smoke.tcl', 'run_post_impl_smoke.tcl'):
                with self.subTest(source_generics=source_generics, name=name):
                    result = self.execute([self.vivado, exported/'scripts'/name,
                                           exported/'project/tflm_ai_dsa_soc.xpr'],
                                          environment=environment, success=False)
                    self.assertIn(error, result.stderr)

    def test_cpu_memory_word_format(self):
        runner = self.work/'prepare_memory.tcl'
        runner.write_text('source [lindex $argv 0]\n'
                          'puts [cpu_memory::write_images {*}[lrange $argv 1 end]]\n')
        self.memory.write_text('/* CPU words */ @0\n0102_0304 8899aabb\n'
                               '@3\n76543210 fedcba98 // two physical rows\n@f\n12345678\n')
        expected = ['01020304', '8899aabb', '00000000', '76543210', 'fedcba98'] + ['00000000'] * 10 + ['12345678']
        for bus in (32, 64):
            cpu32, native = self.work/f'cpu32_{bus}.mem', self.work/f'native_{bus}.mem'
            self.execute([runner, HERE/'cpu_memory.tcl', self.memory, cpu32, native, 16, bus])
            self.assertEqual(cpu32.read_text().splitlines(), expected)
            packed = expected if bus == 32 else [expected[i+1]+expected[i] for i in range(0, 16, 2)]
            self.assertEqual(native.read_text().splitlines(), packed)

    def test_cpu_memory_rejects_invalid_input(self):
        runner = self.work/'prepare_memory.tcl'
        runner.write_text('source [lindex $argv 0]\n'
                          'puts [cpu_memory::write_images {*}[lrange $argv 1 end]]\n')
        for text, depth, bus in [('123456789\n', 16, 64), ('@10\n1234\n', 16, 64),
                                 ('invalid\n', 16, 64), ('0\n', 15, 64),
                                 ('0\n', 0, 32), ('0\n', 16, 128)]:
            with self.subTest(text=text, depth=depth, bus=bus):
                self.memory.write_text(text)
                cpu32, native = self.work/'invalid_cpu32.mem', self.work/'invalid_native.mem'
                self.execute([runner, HERE/'cpu_memory.tcl', self.memory, cpu32, native,
                              depth, bus], success=False)
                self.assertFalse(cpu32.exists())
                self.assertFalse(native.exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--tclsh', default='tclsh')
    parser.add_argument('--picorv32', type=Path, default=os.environ.get('PICORV32_ROOT'))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    ConfigurationTests.directory = out
    ConfigurationTests.tclsh = args.tclsh
    ConfigurationTests.picorv32 = args.picorv32.resolve() if args.picorv32 else None
    sources = [*sorted(HERE.glob('*.tcl')), Path(__file__).resolve(), ROOT/'config/npu_fpga.mk',
               HERE.parent/'rtl/fpga_top.sv', HERE.parent/'sim/fpga_top_behav_smoke_tb.sv',
               HERE.parent/'sim/fpga_top_post_impl_tb.sv']
    before = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    started = time.monotonic()
    with (out/'test.log').open('w') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromTestCase(ConfigurationTests))
    after = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    report = dict(passed=result.wasSuccessful() and before==after,
                  tests=result.testsRun, tcl_processes=len(ConfigurationTests.cases),
                  elapsed_seconds=time.monotonic()-started, source_sha256=before,
                  cases=ConfigurationTests.cases, checks=['Literal Make configuration and environment precedence',
                    'FPGA preset selection and 8 KiB bank requirement before project creation',
                    'AXI width and shared bank propagation to all Vivado project entries',
                    'Exported scripts, configuration snapshot, full data capacity, and relative source paths',
                    'Behavioral and implementation testbench configuration and existing project geometry'],
                  vivado_commands='Tcl command replacements record properties; synthesis and implementation are not executed')
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({key: report[key] for key in ('passed','tests','tcl_processes','elapsed_seconds')}))
    if not report['passed']:
        print((out/'test.log').read_text(), file=sys.stderr)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
