#!/usr/bin/env python3
"""证明偏置加载器范围选择和尾块行数的全部状态与公开输出等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders') / name for name in
           ('bias_loader.sv', 'bias_loader_ctrl.sv', 'bias_loader_buffer.sv')]
MEMORY = Path('rtl/common/regfile.v')
HELPER = Path('rtl/common/parallel_prefix_add.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='bdd7109f')
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    hashes = {str(p): digest(source_root / p) for p in SOURCES + [MEMORY, HELPER]}
    snapshots = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        snapshots[label] = []
        for relative in SOURCES:
            data = (((args.reference_root / relative).read_bytes() if args.reference_root else
                     read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT))
                    if label == 'reference' else (source_root / relative).read_bytes())
            path = folder / relative.name
            path.write_bytes(data)
            snapshots[label].append(path)
    report = {
        'passed': False,
        'reference_rev': (str(args.reference_root.resolve()) if args.reference_root else
                          subprocess.check_output(['git', 'rev-parse', args.reference_rev],
                                                  cwd=ROOT, text=True).strip()),
        'source_root': str(source_root),
        'source_sha256': hashes,
        'snapshot_sha256': {label: {p.name: digest(p) for p in paths}
                            for label, paths in snapshots.items()},
        'inputs_constrained': False,
        'profiles': [],
    }
    profiles = ((4, 32, 1, 1), (16, 32, 12, 4), (16, 64, 28, 32),
                (16, 64, 29, 32), (16, 128, 29, 32), (16, 64, 32, 1))
    for size, bus, count, groups in profiles:
        folder = out / f's{size}_b{bus}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        options = (f'-GSIZE={size} -GBUS_WIDTH={bus} -GCOUNT_WIDTH={count} '
                   f'-GGROUP_BLOCKS_MAX={groups}')
        commands = []
        for label, paths in snapshots.items():
            commands += [
                f'read_slang --top bias_loader {options} ' +
                ' '.join(shlex.quote(str(p)) for p in paths + [source_root / MEMORY, source_root / HELPER]),
                'prep -top bias_loader -flatten', 'memory_map', 'async2sync',
                'opt_clean', f'rename bias_loader {label}', f'design -stash {label}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean',
            'equiv_induct -seq 2', 'equiv_status -assert',
        ]
        script = folder / 'run.ys'
        log = folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run(
                [sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                 '--worker', str(script)], cwd=ROOT, stdout=stream,
                stderr=subprocess.STDOUT, timeout=600)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        case = {
            'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count,
            'GROUP_BLOCKS_MAX': groups,
            'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
            'equivalent_bits': int(match[1]) if match else None,
            'script_sha256': digest(script), 'log_sha256': digest(log),
        }
        report['profiles'].append(case)
        print(json.dumps(case), flush=True)
        if not case['passed']:
            raise RuntimeError(f'Formal comparison did not complete: {log}')
    if hashes != {str(p): digest(source_root / p) for p in SOURCES + [MEMORY, HELPER]}:
        raise RuntimeError('Sources changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
