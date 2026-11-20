#!/usr/bin/env python3
"""证明实际偏置缓冲区的全部状态、输出与同步存储操作逐周期一致。"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
from common import ROOT, REFERENCE, BUFFER, HELPER, digest, snapshot, abstract_storage

PROFILES = [(4, 32, 1, 1), (8, 32, 8, 3), (16, 32, 12, 4),
            (16, 64, 29, 32), (16, 64, 32, 64), (32, 64, 32, 1)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out / 'source', args.reference)
    models = {}
    for label in ['reference', 'current']:
        models[label] = out / f'{label}.sv'
        models[label].write_text(abstract_storage((out / 'source' / label / BUFFER).read_text()))
    report = {'passed': False, 'inputs': inputs, 'input_assumptions': [],
              'memory_return': 'same unconstrained 64-bit value each cycle',
              'storage_relation': 'same initial bits, identical read/write addresses, enables, data and byte masks',
              'profiles': []}
    for size, bus, count, groups in PROFILES:
        folder = out / f's{size}_b{bus}_c{count}_g{groups}'
        folder.mkdir(exist_ok=True)
        commands = []
        for label, source in models.items():
            commands.extend([
                f'read_slang --top bias_loader_buffer -GSIZE={size} -GBUS_WIDTH={bus} '
                f'-GCOUNT_WIDTH={count} -GGROUP_BLOCKS_MAX={groups} {shlex.quote(str(source))} '
                f'{shlex.quote(str(out / "source" / label / HELPER))}',
                'prep -top bias_loader_buffer -flatten', 'memory_map', 'async2sync', 'opt_clean',
                f'rename bias_loader_buffer {label}', f'design -stash {label}'])
        commands.extend([
            'design -copy-from reference -as reference reference',
            'design -copy-from current -as current current',
            'equiv_make reference current equivalent', 'hierarchy -top equivalent',
            'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert'])
        script, log = folder / 'run.ys', folder / 'formal.log'
        script.write_text('\n'.join(commands) + '\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        text = log.read_text()
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
        row = {'SIZE': size, 'BUS_WIDTH': bus, 'COUNT_WIDTH': count, 'GROUP_BLOCKS_MAX': groups,
               'passed': result.returncode == 0 and 'Equivalence successfully proven' in text,
               'equivalent_bits': int(match[1]) if match else None,
               'script_sha256': digest(script), 'log_sha256': digest(log)}
        report['profiles'].append(row)
        print(json.dumps(row), flush=True)
        if not row['passed']:
            raise RuntimeError(text[-6000:])
    for row in inputs['sources']:
        assert digest(ROOT / row['source']) == row['current_sha256']
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
