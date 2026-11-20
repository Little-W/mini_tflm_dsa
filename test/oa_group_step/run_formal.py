#!/usr/bin/env python3
"""检查输出写回步长选择的全部状态转移与公开输出。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/npu/writeback/oa_writer.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='864d659c')
    parser.add_argument('--synthesis', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    original = read_rtl_source(f'{args.reference}:{SOURCE}', text=True)
    current = (ROOT / SOURCE).read_text()
    for label, content in (('reference', original), ('current', current)):
        (out / f'{label}.sv').write_text(content)
    profiles = [(4, 32, 4), (8, 64, 6), (16, 32, 7), (16, 64, 8),
                (16, 64, 16), (16, 64, 29), (16, 64, 32), (32, 64, 32)]
    results = []
    for lanes, bus, count in profiles:
        commands = []
        for label in ('reference', 'current'):
            commands += [f'read_slang --top oa_writer -GVLEN={lanes} -GBUS_WIDTH={bus} '
                         f'-GCOUNT_WIDTH={count} {out / (label + ".sv")}',
                         'prep -top oa_writer -flatten', 'async2sync', 'opt_clean',
                         f'rename oa_writer {label}', f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from current -as current current',
                     'equiv_make reference current proof', 'hierarchy -top proof',
                     'equiv_simple -seq 1', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = out / f'n{lanes}_b{bus}_c{count}.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = script.with_suffix('.log')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        content = log.read_text()
        assert 'Equivalence successfully proven' in content
        match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', content)
        results.append({'lanes': lanes, 'bus_width': bus, 'count_width': count,
                        'equivalent_bits': int(match[1]), 'passed': True,
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print(json.dumps(results[-1]), flush=True)
    assert current == (ROOT / SOURCE).read_text()
    report = {'passed': True, 'reference': args.reference, 'inputs_constrained': False,
              'all_public_outputs_compared': True, 'profiles': results,
              'source_sha256': hashlib.sha256(current.encode()).hexdigest()}
    if args.synthesis:
        cases = {label: {
            'top': 'oa_writer', 'sources': [str(out / f'{label}.sv')],
            'options': ['-D', 'XILINX_FPGA=1', '-GVLEN=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29'],
            'configuration': '生产输出写回控制',
        } for label in ('reference', 'current')}
        config = out / 'cases.json'
        config.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--case-config', str(config), '--cases', 'reference', 'current',
                        '--out', str(out / 'synthesis')], cwd=ROOT, check=True)
        report['synthesis'] = json.loads((out / 'synthesis/summary.json').read_text())
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
