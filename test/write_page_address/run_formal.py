#!/usr/bin/env python3
"""证明写入分页模块的全部状态和公开输出逐周期一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_write_page_guard.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles():
    result = [dict(ADDR_W=32, DATA_W=width, WRITE_OUTSTANDING=count)
              for width in (32, 64) for count in (1, 2, 4, 8)]
    result += [dict(ADDR_W=32, DATA_W=width, WRITE_OUTSTANDING=4)
               for width in (8, 16, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768)]
    result += [dict(ADDR_W=width, DATA_W=64, WRITE_OUTSTANDING=4)
               for width in (12, 16, 40, 64)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT)
                   if label == 'reference' else (ROOT / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    report = dict(reference_ref=args.reference_ref, inputs_constrained=False,
                  scope='Every state element and public output, including inactive cycles and unaligned addresses',
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  runs=[], passed=False)
    for parameters in profiles():
        name = 'addr{ADDR_W}_data{DATA_W}_outstanding{WRITE_OUTSTANDING}'.format(**parameters)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        commands = []
        for label, path in snapshots.items():
            commands += [f'read_slang --top axi_write_page_guard {options} {shlex.quote(str(path))}',
                         'prep -top axi_write_page_guard -flatten', 'async2sync', 'opt_clean',
                         f'rename axi_write_page_guard {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current equivalent', 'hierarchy -top equivalent',
                     'opt_merge', 'equiv_simple -short -seq 1', 'opt_clean',
                     'equiv_induct -seq 2', 'equiv_status -assert']
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
            raise RuntimeError('Complete write page guard equivalence not established')
        row = dict(case=name, parameters=parameters, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if digest(ROOT / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
