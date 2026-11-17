#!/usr/bin/env python3
"""Verify unsliced and sliced PS window scheduling against an independent model."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, default=ROOT / 'rtl/npu/control/ps_window_scheduler.sv')
    parser.add_argument('--test-dir', type=Path, default=HERE)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/ps_compression/window_scheduler')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--reuse-build', action='store_true')
    args = parser.parse_args()
    rtl = args.rtl.resolve()
    test_dir = args.test_dir.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reports = {}
    version = subprocess.check_output([args.verilator, '--version'], text=True).strip()
    for name, cpp in [('unsliced', 'window_scheduler_test.cpp'),
                      ('sliced', 'window_scheduler_fragment_test.cpp')]:
        target = out / name
        target.mkdir(parents=True, exist_ok=True)
        sources = [rtl, test_dir / cpp, test_dir / 'window_scheduler_ref.hpp', Path(__file__).resolve()]
        hashes = {str(path): digest(path) for path in sources}
        binary = target / 'obj/Vps_window_scheduler'
        command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-j', '1',
                   '--top-module', 'ps_window_scheduler', '--Mdir', str(target / 'obj'),
                   '-Wno-fatal', '--output-groups', '0',
                   '-CFLAGS', '-std=c++17 -O1 -fsanitize=undefined -fno-sanitize-recover=all',
                   '-LDFLAGS', '-fsanitize=undefined', '-MAKEFLAGS', '-B', str(rtl), str(test_dir / cpp)]
        started = time.monotonic()
        if args.reuse_build:
            previous = json.loads((target / 'summary.json').read_text())
            if previous['source_sha256'] != hashes or previous['binary_sha256'] != digest(binary):
                raise RuntimeError(f'{name}: saved executable differs from current sources')
            command = previous['compile_command']
        else:
            with (target / 'compile.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(f'{name}: compilation failed; see {target / "compile.log"}')
        result = subprocess.run([str(binary)], text=True, capture_output=True, cwd=ROOT)
        (target / 'run.log').write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name}: {result.stdout}{result.stderr}')
        report = json.loads(result.stdout.strip().splitlines()[-1])
        if not report['passed'] or hashes != {str(path): digest(path) for path in sources}:
            raise RuntimeError(f'{name}: validation failed or source files changed')
        commands = [line for line in (target / 'compile.log').read_text().splitlines()
                    if ' -c ' in line and ' -o ' in line]
        if not commands or any('-fsanitize=undefined' not in line for line in commands):
            raise RuntimeError(f'{name}: a translation unit lacks UBSan')
        report.update(source_sha256=hashes, binary_sha256=digest(binary),
                      compile_command=command, run_command=[str(binary)],
                      undefined_behavior_sanitizer=True, sanitized_translation_units=len(commands),
                      elapsed_seconds=time.monotonic() - started, verilator=version,
                      input_format='One matrix row contains zero to four 128-bit words; per-bank reservation uses reserve_rows.')
        (target / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        reports[name] = report
        print(json.dumps({'test': name, **{key: value for key, value in report.items()
                                         if key not in ('source_sha256', 'compile_command')}}), flush=True)
    summary = dict(passed=True, cases=sum(r['cases'] for r in reports.values()),
                   commands=sum(r['commands'] for r in reports.values()), tests=reports)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
