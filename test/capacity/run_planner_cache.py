#!/usr/bin/env python3
"""Verify address equivalence and independent RAW keys in the schedule cache."""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/planner_cache')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    profiles = []
    for profile in ('standalone', 'nmsis'):
        binary = out / profile
        command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-Wno-unused-function', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                   '-DDSA_MMIO_CUSTOM', '-DDSA_PS_COMPRESS=1', '-DDSA_PS_POOL_BYTES=12288']
        if profile == 'nmsis':
            command += ['-DTEST_NMSIS', '-I', str(ROOT / 'drivers/tflm/NMSIS/NN/Include')]
        command += ['-I', str(ROOT / 'drivers'), str(ROOT / 'test/capacity/test_planner_cache.c'),
                    '-o', str(binary)]
        compiled = subprocess.run(command, text=True, capture_output=True)
        (out / f'{profile}_build.log').write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=60)
        (out / f'{profile}_run.log').write_text(result.stdout + result.stderr)
        print(profile, result.stdout, end='', flush=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        profiles.append({'profile': profile, 'passed': True, 'observations': result.stdout.strip()})
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'profiles': profiles}, indent=2) + '\n')


if __name__ == '__main__':
    main()
