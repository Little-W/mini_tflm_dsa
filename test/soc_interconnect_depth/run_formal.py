#!/usr/bin/env python3
"""在不限制公开输入的条件下，证明互连全部状态与输出逐周期一致。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axi_interconnect.sv')
REFERENCE = '2297cb12deac56b476f9a2a656da4038a9d8a75c'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles():
    result = [dict(ADDR_WIDTH=32, DATA_WIDTH=width, CPU_MEM_DP=65536,
                   READ_OUTSTANDING=count, WRITE_OUTSTANDING=count)
              for width in (32, 64) for count in (1, 4)]
    result += [dict(ADDR_WIDTH=width, DATA_WIDTH=64, CPU_MEM_DP=capacity,
                    READ_OUTSTANDING=3, WRITE_OUTSTANDING=5,
                    CPU_RAM_BASE=base, NPU_AXIL_BASE=npu)
               for width, capacity, base, npu in
               [(40, 1031, 8195, 268435456), (64, 1, 0, 0),
                (32, 524288, -1048576, 268435456),
                (32, 1031, 33554432, 33554432)]]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (((args.reference_root / SOURCE).read_bytes() if args.reference_root else
                    subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT))
                   if label == 'reference' else (args.source_root / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    report = dict(reference_ref=str(args.reference_root.resolve()) if args.reference_root else args.reference_ref,
                  source_root=str(args.source_root.resolve()), inputs_constrained=False,
                  scope='Every state element and public output, including arbitrary handshake combinations',
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  runs=[], passed=False)
    for index, parameters in enumerate(profiles()):
        name = 'case' + str(index)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        commands = []
        for label, path in snapshots.items():
            commands += [f'read_slang --top soc_axi_interconnect {options} {shlex.quote(str(path))}',
                         'prep -top soc_axi_interconnect -flatten', 'memory_map', 'async2sync', 'opt_clean',
                         f'rename soc_axi_interconnect {label}', f'design -stash {label}']
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
            raise RuntimeError('Complete interconnect equivalence not established')
        row = dict(case=name, parameters=parameters, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if digest(args.source_root / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
