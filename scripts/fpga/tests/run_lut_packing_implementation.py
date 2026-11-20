#!/usr/bin/env python3
"""验证普通 LUT 共用位置的实际布局、布线和 INIT。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--nextpnr', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True, help='nextpnr 的 xilinx 源码目录')
    parser.add_argument('--chipdb', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--through', choices=('place', 'route'), default='route')
    args = parser.parse_args()
    scripts = Path(__file__).resolve().parent
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    binary = args.nextpnr.resolve()
    chipdb = args.chipdb.resolve()
    source = args.source.resolve()
    env = dict(os.environ, XC7_FRACTURE_LUTS='1', XC7_CARRY_DIRECT_DI='1')
    base = [str(binary), '--chipdb', str(chipdb), '--freq', '150', '--seed', '1',
            '--strict-timing-graph', '--timing-allow-fail']
    summary = {'nextpnr_sha256': digest(binary), 'chipdb_sha256': digest(chipdb),
               'through': args.through, 'cases': {}}
    prepare = [sys.executable, str(scripts / 'prepare_cases.py')]
    with (output / 'generate.log').open('w') as log:
        subprocess.run(prepare + ['--out', str(output / 'inputs')],
                       check=True, stdout=log, stderr=subprocess.STDOUT, env=env)
    cases = json.loads((output / 'inputs/manifest.json').read_text())

    for name, case in cases.items():
        folder = output / name
        folder.mkdir(exist_ok=True)
        inputs = Path(case['directory'])
        results = {'expected_same_position_legal': case['same_position_legal']}
        summary['cases'][name] = results

        def run(stage, parameters):
            command = base + parameters
            start = time.monotonic()
            with (folder / f'{stage}.log').open('w') as log:
                process = subprocess.run(command, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, timeout=180)
            results[stage] = {'command': command, 'return_code': process.returncode,
                              'elapsed_seconds': round(time.monotonic() - start, 3)}
            return process.returncode

        assert run('pack', ['--json', str(inputs / 'implementation.json'),
                           '--xdc', str(inputs / 'pins.xdc'), '--pack-only',
                           '--write', str(folder / 'packed.json')]) == 0
        subprocess.run(prepare + ['--constrain', str(folder / 'packed.json'),
                                 '--write', str(folder / 'packed_pair.json')], check=True)
        code = run('place', ['--json', str(folder / 'packed_pair.json'), '--no-pack',
                            '--no-route', '--write', str(folder / 'placed.json')])
        if not case['same_position_legal']:
            assert code != 0
            assert 'Unable to find legal placement' in (folder / 'place.log').read_text()
        else:
            assert code == 0
            physical = folder / 'placed.json'
            if args.through == 'route':
                physical = folder / 'routed.json'
                assert run('route', ['--json', str(folder / 'placed.json'), '--no-pack',
                                     '--no-place', '--write', str(physical)]) == 0
            check = [sys.executable, str(scripts / 'check_json_init.py'),
                     '--source', str(source), '--packed', str(folder / 'packed.json'),
                     '--physical', str(physical), '--out', str(folder / 'init_check')]
            with (folder / 'init_check.log').open('w') as log:
                subprocess.run(check, check=True, stdout=log, stderr=subprocess.STDOUT)
            results['logical_function'] = json.loads((folder / 'init_check/summary.json').read_text())
            assert results['logical_function']['logical_luts'] == 2
            assert results['logical_function']['physical_lut_sites'] == 1
            results['physical_json_sha256'] = digest(physical)
        results['passed'] = True
        (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(name, 'passed', flush=True)


if __name__ == '__main__':
    main()
