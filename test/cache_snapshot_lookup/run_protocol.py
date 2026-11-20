#!/usr/bin/env python3
"""顺序执行既有缓存协议测试并保留每组报告与可执行文件。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--profiles', nargs='+', default=['4:2', '2:2', '4:1', '1:2'])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['MAKEFLAGS'] = 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E'
    reports = []
    for profile in args.profiles:
        depth, ways = map(int, profile.split(':'))
        folder = out / f'demand{depth}_ways{ways}'
        command = [sys.executable, str(ROOT / 'test/cache_pipeline/run.py'), '--out', str(folder),
                   '--verilator', args.verilator, '--jobs', '1', '--profiles', profile]
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        result = json.loads((folder / 'summary.json').read_text())
        if not result['passed'] or len(result['profiles']) != 1:
            raise RuntimeError('Incomplete cache protocol verification')
        reports.append({'profile': profile, 'passed': True, 'report': result,
                        'report_sha256': hashlib.sha256((folder / 'summary.json').read_bytes()).hexdigest()})
        binary = folder / f'd{depth}_w{ways}/obj/Vtb_cache_pipeline'
        for path in binary.parent.iterdir():
            if path != binary and path.is_file():
                path.unlink()
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'makeflags': env['MAKEFLAGS'],
                                                'profiles': reports}, indent=2) + '\n')


if __name__ == '__main__':
    main()
