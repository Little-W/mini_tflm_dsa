#!/usr/bin/env python3
"""比较完整线性 DMA 的公开输出、时钟状态和展开后的描述符存储。"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--sizes', type=int, nargs='+', default=[16])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    originals = {'reference': args.reference.resolve(), 'current': args.candidate.resolve()}
    paths = {}
    inputs = {}
    for label, original in originals.items():
        path = out / (label + '.sv')
        path.write_bytes(original.read_bytes())
        paths[label] = path
        inputs[label] = {'path': str(original), 'sha256': digest(path)}
    helpers = []
    for name in ('regfile.v', 'add_equal.sv', 'add_equal_bit.sv',
                 'add_equal_reduce.sv', 'zero_reduce.sv'):
        path = out / name
        path.write_bytes((ROOT / 'rtl/common' / name).read_bytes())
        helpers.append(path)
    report = {'passed': False, 'inputs': inputs,
              'helper_sha256': {path.name: digest(path) for path in helpers},
              'input_assumptions': [],
              'scope': 'Every public output, every shared clocked state, and expanded memories; all external input sequences',
              'profiles': []}
    for size, bus, read_outstanding, write_outstanding, contexts in itertools.product(args.sizes, (32, 64), (1, 4), (1, 4), (1, 4)):
        name = f's{size}_b{bus}_r{read_outstanding}_w{write_outstanding}_c{contexts}'
        options = ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1', f'-GSIZE={size}',
                   f'-GBUS_WIDTH={bus}', f'-GREAD_OUTSTANDING={read_outstanding}',
                   f'-GWRITE_OUTSTANDING={write_outstanding}', f'-GRD_CONTEXT_DEPTH={contexts}']
        commands = []
        for label, path in paths.items():
            commands += [
                'read_slang --top axi_linear_block_dma ' + shlex.join(options + list(map(str, [path] + helpers))),
                'prep -top axi_linear_block_dma -flatten', 'memory_map', 'opt_clean',
                f'rename axi_linear_block_dma {label}', f'design -stash {label}',
            ]
        commands += [
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'expose -dff -shared reference current', 'async2sync', 'opt_clean',
            'rename -hide reference/w:* current/w:*',
            'equiv_make reference current comparison', 'hierarchy -top comparison',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert',
        ]
        script, log = out / (name + '.ys'), out / (name + '.log')
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                                    cwd=ROOT, timeout=300)
        text = log.read_text()
        matched = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'size': size, 'bus_width': bus, 'read_outstanding': read_outstanding,
               'write_outstanding': write_outstanding, 'read_context_depth': contexts,
               'equivalent_bits': int(matched[1]) if matched else None,
               'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
               'script_sha256': digest(script), 'log_sha256': digest(log)}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(f'完整 DMA 等价检查未完成：{log}')
    for label, path in originals.items():
        if digest(path) != inputs[label]['sha256']:
            raise RuntimeError(f'运行期间输入源码发生变化：{path}')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
