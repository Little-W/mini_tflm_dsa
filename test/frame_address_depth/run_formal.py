#!/usr/bin/env python3
"""Prove complete frame address state and outputs for unrestricted inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/frame_address_prepare.sv')
HELPER = Path('rtl/common/parallel_prefix_add.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles():
    return [dict(p_size=size, p_ready_mask_abort=mask)
            for size, mask in ((1,0),(1,1),(2,1),(3,1),(16,0),(16,1),(17,1),(32,1),(64,1))]


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
                  scope='Every state element and public output; arbitrary start, abort, reset and result acceptance',
                  helper_sha256=digest(ROOT / HELPER),
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  runs=[], passed=False)
    for index, parameters in enumerate(profiles()):
        name = 'case' + str(index)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        commands = []
        for label, path in snapshots.items():
            commands += [f'read_slang --top frame_address_prepare {options} {shlex.quote(str(path))} '
                         f'{shlex.quote(str(ROOT / HELPER))}',
                         'prep -top frame_address_prepare -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename frame_address_prepare {label}', f'design -stash {label}']
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
            raise RuntimeError('Complete frame address equivalence not established')
        row = dict(case=name, parameters=parameters, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if digest(ROOT / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during verification')
    if digest(ROOT / HELPER) != report['helper_sha256']:
        raise RuntimeError('Adder changed during verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
