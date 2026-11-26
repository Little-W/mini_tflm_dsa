#!/usr/bin/env python3
"""验证偏置范围检查的完整端口等价、参数边界和四态输入传播。"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
OUT = args.out.resolve()
OUT.mkdir(parents=True, exist_ok=True)
REFERENCE = 'c42f5ff9'
SOURCE = 'rtl/npu/loaders/bias_request_end_compare.sv'
REF = OUT / 'reference.sv'
REF.write_text(subprocess.check_output(['git', 'show', REFERENCE + ':' + SOURCE], cwd=ROOT, text=True))
ACTUAL = ROOT / SOURCE
resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
dependencies = resolve([ACTUAL], ROOT)[1:]
WIDTHS = (1, 7, 22, 23, 24, 29, 31, 32, 34, 44, 45, 46, 47)
MODES = [('generic', []), ('synthesis', ['-DSYNTHESIS=1']),
         ('fpga', ['-DXILINX_FPGA=1']), ('fpga_synthesis', ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'])]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=300)


def formal(job):
    mode, flags, width = job
    key = f'{mode}_width{width}'
    commands = []
    for name, source in [('reference', REF), ('candidate', ACTUAL)]:
        commands += ['read_slang --top bias_request_end_compare ' + shlex.join(
            [*flags, '-Gp_count_width=' + str(width), str(source), *map(str, dependencies)]),
            'setattr -mod -unset keep_hierarchy', 'setattr -unset keep_hierarchy',
            'prep -top bias_request_end_compare -flatten', 'rename -top ' + name, 'design -stash ' + name]
    commands += ['design -copy-from reference -as reference reference',
                 'design -copy-from candidate -as candidate candidate',
                 'equiv_make reference candidate proof', 'hierarchy -top proof',
                 'equiv_simple', 'equiv_status -assert']
    script, log = OUT / (key + '.ys'), OUT / (key + '.log')
    script.write_text('\n'.join(commands) + '\n')
    execute([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
    assert 'Equivalence successfully proven!' in log.read_text()
    print(key + ' PASS', flush=True)
    return {'mode': mode, 'count_width': width, 'passed': True, 'log_sha256': sha(log)}


test_reference = OUT / 'reference_renamed.sv'
test_reference.write_text(REF.read_text().replace('module bias_request_end_compare', 'module bias_range_reference', 1))
bench = OUT / 'tb.sv'
bench.write_text('''module tb;
reg[63:0] base,count,finish;
wire[''' + str(len(WIDTHS)-1) + ''':0] expected,actual;
integer checks=0;
''' + '\n'.join(f'''
bias_range_reference #(.p_count_width({width})) ref_{width}(
 .i_base(base[{width-1}:0]),.i_count(count[{width-1}:0]),.i_end(finish[{width}:0]),.o_outside(expected[{index}]));
bias_request_end_compare #(.p_count_width({width})) dut_{width}(
 .i_base(base[{width-1}:0]),.i_count(count[{width-1}:0]),.i_end(finish[{width}:0]),.o_outside(actual[{index}]));
''' for index, width in enumerate(WIDTHS)) + '''
initial begin
for(integer sample=0;sample<65536;sample++)begin
 base={$urandom,$urandom};count={$urandom,$urandom};finish={$urandom,$urandom};
 case(sample%32)
 0:begin base=0;count=0;finish=0;end
 1:finish=base+count;
 2:finish=base+count-1;
 3:finish=base+count+1;
 4:begin base='1;count='1;end
 5:base[sample%48]=1'bx;
 6:count[sample%48]=1'bz;
 7:finish[sample%48]=1'bx;
 8:base='x;
 9:count='z;
 10:finish='x;
 11:begin base=0;count[sample%48]=1'bx;finish=0;end
 12:begin base='1;count=0;finish[sample%48]=1'bz;end
 13:begin base[sample%48]=1'bz;count[(sample>>6)%48]=1'bx;end
 default:begin end
 endcase
 #1;
 if(actual!==expected)$fatal(1,"偏置范围结果不同 sample=%0d expected=%b actual=%b",sample,expected,actual);
 checks=checks+''' + str(len(WIDTHS)) + ''';
end
$display("PASS comparisons=%0d",checks);$finish;
end
endmodule
''')


def four_state(mode):
    name, flags = mode
    executable, log = OUT / (name + '_simulation'), OUT / (name + '_run.log')
    execute(['iverilog', '-g2012', *flags, '-s', 'tb', '-o', executable,
             test_reference, ACTUAL, *dependencies, bench], OUT / (name + '_compile.log'))
    execute(['vvp', executable], log)
    count = 65536 * len(WIDTHS)
    assert f'PASS comparisons={count}' in log.read_text()
    print(name + ' four-state PASS', flush=True)
    return {'mode': name, 'passed': True, 'comparisons': count, 'log_sha256': sha(log)}


with ThreadPoolExecutor(max_workers=2) as workers:
    proofs = list(workers.map(formal, [(mode, flags, width) for mode, flags in MODES for width in WIDTHS]))
with ThreadPoolExecutor(max_workers=2) as workers:
    simulations = list(workers.map(four_state, MODES))
unchanged = {}
for relative in ('rtl/npu/loaders/bias_loader.sv', 'rtl/npu/loaders/bias_loader_ctrl.sv',
                 'rtl/npu/loaders/bias_loader_buffer.sv', 'rtl/npu/loaders/bias_resident_qualify.sv'):
    historical = subprocess.check_output(['git', 'show', REFERENCE + ':' + relative], cwd=ROOT)
    assert (ROOT / relative).read_bytes() == historical, relative
    unchanged[relative] = sha(ROOT / relative)
report = {'passed': True, 'formal': proofs, 'four_state': simulations,
          'reference_commit': REFERENCE, 'ports_unconstrained': True, 'all_public_outputs_compared': True,
          'parent_modules_unchanged': unchanged,
          'source_sha256': {'reference': sha(REF), 'candidate': sha(ACTUAL),
                            **{str(path.relative_to(ROOT)): sha(path) for path in dependencies}},
          'test_sha256': sha(Path(__file__))}
(OUT / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
