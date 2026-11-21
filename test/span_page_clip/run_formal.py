#!/usr/bin/env python3
"""证明 AXI 分段读取的页末截短、地址递增及完整状态和输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_axi_span_reader.sv')
REFERENCE = '51c390c51884c686bc1a08e1b32f40f9047b7b1b'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profiles():
    result = []
    for bus in (32, 64, 128, 1024):
        word = bus // 8
        for limit in sorted({1, 3, word - 1, word, word + 1, 16, 255, 256, 257, 65535}):
            result.append(dict(BUS_WIDTH=bus, MAX_REQUEST_BYTES=limit,
                               DMA_MAX_BYTES=256 * word))
    for bus in (32, 64):
        for beats in (1, 2, 4, 8, 16, 32, 64, 128):
            result.append(dict(BUS_WIDTH=bus, MAX_REQUEST_BYTES=65535,
                               DMA_MAX_BYTES=beats * bus // 8))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT,
                        help='包含待验证 RTL 的独立源码目录')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT)
                   if label == 'reference' else (args.source_root.resolve() / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    report = dict(reference_ref=args.reference_ref, inputs_constrained=False,
                  scope='All public outputs and every state element, including inactive-cycle outputs',
                  source_sha256={name: digest(path) for name, path in snapshots.items()},
                  runs=[], passed=False)
    for parameters in profiles():
        name = 'bus{BUS_WIDTH}_request{MAX_REQUEST_BYTES}_dma{DMA_MAX_BYTES}'.format(**parameters)
        options = ' '.join(f'-G{key}={value}' for key, value in parameters.items())
        commands = []
        for label, path in snapshots.items():
            commands += [f'read_slang --top conv_axi_span_reader {options} {shlex.quote(str(path))}',
                         'prep -top conv_axi_span_reader -flatten', 'async2sync', 'opt_clean',
                         f'rename conv_axi_span_reader {label}', f'design -stash {label}']
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
                           stderr=subprocess.STDOUT, check=True, timeout=120)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        if not match or int(match[2]) or 'Equivalence successfully proven' not in text:
            raise RuntimeError('Complete span reader equivalence not established')
        row = dict(case=name, parameters=parameters, passed=True,
                   equivalent_bits=int(match[1]), log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
    if digest(args.source_root.resolve() / SOURCE) != report['source_sha256']['current']:
        raise RuntimeError('Source changed during verification')
    report['passed'] = True
    report['equivalent_bits'] = sum(row['equivalent_bits'] for row in report['runs'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
