#!/usr/bin/env python3
"""验证固定层数的舍入进位，覆盖完整有符号输入和全部移位量。"""
import argparse
import hashlib
import json
import runpy
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/conv/vector_round_shift.sv'
DEPENDENCIES = runpy.run_path(str(ROOT / "scripts/rtl/source_files.py"))["with_dependencies"]


def normalized(source):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', source, flags=re.S))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e6fd2b1f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    original = read_rtl_source(revision + ':' + SOURCE, cwd=ROOT, text=True)
    candidate = (ROOT / SOURCE).read_text()
    ref_fixed = original[original.index('  input logic clk,'):original.index('  // 八个八位部分')]
    cur_fixed = candidate[candidate.index('  input logic clk,'):candidate.index('  // 高字节产生进位时')]
    cur_fixed = cur_fixed.replace('  logic [7:0] byte_carry;\n', '')
    assert normalized(ref_fixed) == normalized(cur_fixed)
    reference = out / 'reference.sv'
    reference.write_text(original)
    current = ROOT / SOURCE
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = out / 'lut6_model.sv'
    block = re.search(r'^module LUT6\b.*?^endmodule', library.read_text(), re.M | re.S).group()
    model.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', block, flags=re.S) + '\n')
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (current, Path(__file__).resolve())}
    report = {'reference_revision': revision, 'source_sha256': hashes,
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'shifts_and_middle_registers_unchanged': True, 'input_constraints': None,
              'input_scope': 'All signed 64-bit values and all six-bit shift amounts on every cycle.',
              'runs': []}
    for mode in ('fpga', 'generic'):
        for middle in (0, 1):
            folder = out / f'{mode}_middle{middle}'
            folder.mkdir(exist_ok=True)
            define = '' if mode == 'fpga' else ' -D ASIC_SYNTHESIS=1'
            commands = []
            for label, source in (('reference', reference), ('current', current)):
                sources = ' '.join(shlex.quote(str(p)) for p in DEPENDENCIES([source, model], ROOT))
                commands.extend([f'read_slang -D SYNTHESIS=1{define} --top vector_round_shift -GREGISTER_MIDDLE={middle} {sources}',
                                 'prep -top vector_round_shift -flatten', 'opt -full',
                                 'rename vector_round_shift ' + label, 'design -stash ' + label])
            commands.extend(['design -copy-from reference -as reference reference',
                             'design -copy-from current -as current current',
                             'equiv_make reference current comparison', 'hierarchy -top comparison',
                             'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2',
                             'equiv_status -assert'])
            script = folder / 'run.ys'
            script.write_text('\n'.join(commands) + '\n')
            log = folder / 'formal.log'
            with log.open('w') as output:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                         '--worker', str(script)], cwd=ROOT, stdout=output,
                                        stderr=subprocess.STDOUT, timeout=180)
            passed = result.returncode == 0 and 'Equivalence successfully proven' in log.read_text()
            if not passed:
                raise RuntimeError(f'Rounding equivalence did not complete: {log}')
            row = {'implementation': mode, 'REGISTER_MIDDLE': middle, 'passed': True,
                   'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
            report['runs'].append(row)
            print(json.dumps(row), flush=True)
    assert hashes == {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in hashes}
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
