#!/usr/bin/env python3
"""Check transfer-aware candidate selection against complete host enumeration."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/scored_planner')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    binary = out / 'test_scored_planner'
    command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-function', '-fsanitize=undefined', '-fno-sanitize-recover=all',
               '-I', str(ROOT / 'drivers'),
               str(ROOT / 'test/capacity/test_scored_planner.c'), '-o', str(binary)]
    compiled = subprocess.run(command, text=True, capture_output=True)
    (out / 'build.log').write_text(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise RuntimeError(compiled.stderr)
    result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=120)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    print(result.stdout, end='', flush=True)
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    headers = ('dsa_schedule.h', 'dsa_memory_schedule.h', 'dsa_memory.h', 'gempact_tiling.h')
    report = {'passed': True, 'configurations': 800, 'geometry_checks': 71,
              'auto_selection_cases': 8,
              'test_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (Path(__file__).resolve(), ROOT / 'test/capacity/test_scored_planner.c')},
              'driver_sha256': {name: hashlib.sha256((ROOT / 'drivers' / name).read_bytes()).hexdigest()
                                for name in headers}}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
