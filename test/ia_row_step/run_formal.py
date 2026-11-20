#!/usr/bin/env python3
"""提取实际行步长组合逻辑，检查全部数据及复用数量输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/ia_loader_ctrl.sv'
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text):
    marker = '  if (REG_WIDTH >= 7) begin : g_encoded_row_step'
    if marker in text:
        start = text.index(marker)
    else:
        start = text.index('  always_comb begin\n    unique case (cfg_ia_reuse_num)')
    end = text.index('\n  always_ff', start)
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='eeac204b')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {'reference': read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT, text=True),
               'current': (ROOT / SOURCE).read_text()}
    snapshots = {}
    for name, text in sources.items():
        path = out / (name + '.sv')
        path.write_text(f'module row_step_{name} #(parameter int REG_WIDTH=32) (\n'
            '    input logic [REG_WIDTH-1:0] tile_row_step_b_comb, cfg_ia_reuse_num,\n'
            '    output logic [REG_WIDTH-1:0] l2_group_row_step_b_comb);\n' +
            extract(text) + '\nendmodule\n')
        snapshots[name] = path
    report = dict(passed=False, reference=args.reference, inputs_constrained=False,
                  source_sha256={name: hashlib.sha256(text.encode()).hexdigest()
                                 for name, text in sources.items()}, runs=[])
    for width in (1, 2, 3, 6, 7, 8, 16, 32, 48, 64):
        commands = []
        for name, path in snapshots.items():
            commands += [f'read_slang --top row_step_{name} -GREG_WIDTH={width} ' + shlex.quote(str(path)),
                         f'prep -top row_step_{name} -flatten',
                         f'rename row_step_{name} {name}', f'design -stash {name}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'miter -equiv -flatten -make_outputs reference current equivalent',
                     'hierarchy -top equivalent',
                     'sat -verify -prove trigger 0 -show-inputs -show-outputs']
        script = out / f'width{width}.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = out / f'width{width}.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT,
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=120)
        row = dict(width=width, input_bits=2*width,
                   passed=result.returncode == 0 and 'no model found: SUCCESS!' in log.read_text(),
                   log_sha256=digest(log))
        report['runs'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError('Row step comparison did not complete: ' + str(log))
    if sources['current'] != (ROOT / SOURCE).read_text():
        raise RuntimeError('RTL changed during verification')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
