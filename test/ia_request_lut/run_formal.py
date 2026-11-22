#!/usr/bin/env python3
"""证明普通 RTL 坐标等式和完整 IA 加载器的全部状态转移。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from models import prepare_models

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source, read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders') / (name + '.sv')
           for name in ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr')]
CASES = {
    'production': ['-DXILINX_FPGA=1', '-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29',
                   '-GCACHE_BLOCKS=32', '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1'],
    'full_count': ['-DXILINX_FPGA=1', '-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=32',
                   '-GCACHE_BLOCKS=32', '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1'],
    'large_cache': ['-DXILINX_FPGA=1', '-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29',
                    '-GCACHE_BLOCKS=64', '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1'],
    'local_size3': ['-DXILINX_FPGA=1', '-GSIZE=3', '-GBUS_WIDTH=32', '-GCOUNT_WIDTH=8',
                    '-GCACHE_BLOCKS=4', '-GEXTERNAL_RAM=0', '-GORDERED_JOB=1'],
    'asic': ['-DASIC_SYNTHESIS=1', '-GSIZE=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29',
             '-GCACHE_BLOCKS=32', '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1'],
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_script(out, name, commands):
    script = out / (name + '.ys')
    log = out / (name + '.log')
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=600)
    return result.returncode, log


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='75f9862e')
    parser.add_argument('--cases', nargs='+', choices=tuple(CASES), default=list(CASES))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    model, model_info = prepare_models(out)
    common = sorted(path for path in (ROOT / 'rtl/common').glob('*')
                    if path.suffix in ('.sv', '.v'))
    summary = {'reference_rev': args.reference_rev, 'source_input_constraints': False,
               'source_sha256': {str(path): digest(ROOT / path) for path in SOURCES},
               'common_sha256': {str(path.relative_to(ROOT)): digest(path) for path in common},
               'primitive_models': model_info, 'equality_runs': [], 'runs': []}
    snapshots = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in SOURCES:
            data = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else read_current_source(ROOT / relative).encode())
            path = folder / relative.name
            path.write_bytes(data)
            snapshots[label].append(path)

    def save():
        summary['passed'] = (all(row['passed'] for row in summary['equality_runs']) and
                             all(row['passed'] for row in summary['runs']))
        (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')

    miter = out / 'equality.sv'
    miter.write_text('''module equality #(parameter int p_width=28)(
        input logic [p_width-1:0] i_a, i_b, i_target,
        input logic i_carry_in, output logic o_equivalent);
        logic [p_width-1:0] sum;
        logic result;
        assign sum = i_a + i_b + p_width'(i_carry_in);
        add_equal #(.p_width(p_width)) u_equal(
            .i_a(i_a), .i_b(i_b), .i_target(i_target),
            .i_carry_in(i_carry_in), .o_equal(result));
        assign o_equivalent = result == (sum == i_target);
    endmodule
''')
    for width in (1, 2, 27, 28, 30, 32, 64):
        commands = [f'read_slang --top equality -Gp_width={width} ' +
                    ' '.join(shlex.quote(str(path)) for path in
                             (ROOT / 'rtl/common/add_equal.sv', model, miter)),
                    'prep -top equality -flatten',
                    'sat -verify -prove o_equivalent 1 -show-inputs -show-outputs']
        returncode, log = run_script(out, 'equality_' + str(width), commands)
        row = {'width': width, 'unconstrained_input_bits': width * 3 + 1,
               'passed': returncode == 0 and 'no model found: SUCCESS!' in log.read_text(),
               'log_sha256': digest(log)}
        summary['equality_runs'].append(row)
        save()
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Coordinate equality proof did not complete: ' + str(log))

    for name in args.cases:
        commands = []
        for label in ('reference', 'current'):
            commands += ['read_slang --top ia_loader ' + ' '.join(CASES[name]) + ' ' +
                         ' '.join(shlex.quote(str(path)) for path in snapshots[label] + common + [model]),
                         'prep -top ia_loader -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         'rename ia_loader ' + label, 'design -stash ' + label]
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        returncode, log = run_script(out, name, commands)
        text = log.read_text()
        count = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'name': name, 'parameters': CASES[name],
               'passed': returncode == 0 and 'Equivalence successfully proven' in text,
               'equivalent_bits': int(count[1]) if count else None, 'log_sha256': digest(log)}
        summary['runs'].append(row)
        save()
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Full-state proof did not complete: ' + str(log))
    if summary['source_sha256'] != {str(path): digest(ROOT / path) for path in SOURCES}:
        raise RuntimeError('Sources changed during verification')


if __name__ == '__main__':
    main()
