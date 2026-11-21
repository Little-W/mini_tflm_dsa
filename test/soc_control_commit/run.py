#!/usr/bin/env python3
"""验证 SoC 控制寄存器的独立 AXI Lite 通道、背压及复位。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/soc_axil_ctrl.sv')
REFERENCE = 'fe0ed2325743c9b353b74377fbe7b4a1e9d19d64'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default=REFERENCE)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    snapshots = {}
    for label in ('reference', 'current'):
        path = out / label / SOURCE.name
        path.parent.mkdir(exist_ok=True)
        content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{SOURCE}'], cwd=ROOT)
                   if label == 'reference' else (args.source_root / SOURCE).read_bytes())
        path.write_bytes(content)
        snapshots[label] = path
    bench = Path(__file__).with_name('tb_soc_control.sv')
    report = {'passed': False, 'reference_ref': args.reference_ref,
              'source_sha256': {label: digest(path) for label, path in snapshots.items()},
              'testbench_sha256': digest(bench), 'runs': []}
    for address_width, data_width in ((32, 32), (40, 32), (64, 64)):
        for label in ('reference', 'current'):
            name = f'{label}_{address_width}_{data_width}'
            binary, log = out / (name + '.vvp'), out / (name + '.log')
            command = ['iverilog', '-g2012', '-s', 'tb_soc_control',
                       f'-Ptb_soc_control.AW={address_width}',
                       f'-Ptb_soc_control.DW={data_width}', '-o', str(binary),
                       str(snapshots[label]), str(bench)]
            with (out / (name + '.build.log')).open('w') as stream:
                subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=120)
            result = subprocess.run(['vvp', str(binary)], stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, timeout=120)
            log.write_text(result.stdout)
            result.check_returncode()
            match = re.search(r'SOC_CTRL_PASS writes=(\d+) reads=(\d+) resets=(\d+) cycles=(\d+)',
                              result.stdout)
            if not match:
                raise RuntimeError('AXI Lite 事务验证未完成')
            row = {'label': label, 'address_width': address_width, 'data_width': data_width,
                   'writes': int(match[1]), 'reads': int(match[2]), 'resets': int(match[3]),
                   'cycles': int(match[4]), 'log_sha256': digest(log), 'passed': True}
            report['runs'].append(row)
            print(json.dumps(row), flush=True)
    report['passed'] = True
    cases = {label: {'top': 'soc_axil_ctrl', 'sources': [str(path)],
                    'options': ['-DSYNTHESIS=1', '-GAXIL_ADDR_WIDTH=32', '-GAXIL_DATA_WIDTH=32'],
                    'parameters': {'AXIL_ADDR_WIDTH': 32, 'AXIL_DATA_WIDTH': 32},
                    'configuration': 'SoC control AXI Lite register interface'}
             for label, path in snapshots.items()}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
