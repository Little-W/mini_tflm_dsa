#!/usr/bin/env python3
"""Check shared-memory scheduling against fixed AXI32/64 transfer counts."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/shared_axi_schedule')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    profiles = []
    for name, flags, bits in (
            ('fallback', [], 32),
            ('configured', ['-DNPU_CONFIG_NPU_AXI_DATA_WIDTH=64'], 64),
            ('explicit', ['-DNPU_CONFIG_NPU_AXI_DATA_WIDTH=64', '-DDSA_SCHEDULE_AXI_DATA_BITS=32'], 32)):
        binary = out / name
        command = ['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-Wno-unused-function', '-fsanitize=undefined', '-fno-sanitize-recover=all',
                   *flags, f'-DTEST_EXPECT_AXI_DATA_BITS={bits}', '-I', str(ROOT / 'drivers'),
                   str(ROOT / 'test/capacity/test_shared_axi_schedule.c'), '-o', str(binary)]
        compiled = subprocess.run(command, text=True, capture_output=True)
        (out / f'{name}_build.log').write_text(compiled.stdout + compiled.stderr)
        if compiled.returncode:
            raise RuntimeError(compiled.stderr)
        result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=30)
        (out / f'{name}_run.log').write_text(result.stdout + result.stderr)
        print(name, result.stdout, end='', flush=True)
        if result.returncode:
            raise RuntimeError(result.stderr or result.stdout)
        profiles.append({'name': name, 'default_axi_data_bits': bits, 'passed': True,
                         'compile_command': command, 'observations': result.stdout.strip()})
    names = ('dsa_schedule.h', 'dsa_memory_schedule.h', 'gempact_tiling.h', 'dsa_memory.h')
    report = {'passed': True, 'transfer_cases': 42, 'invalid_bus_configs': 18, 'profiles': profiles,
              'driver_sha256': {name: hashlib.sha256((ROOT / 'drivers' / name).read_bytes()).hexdigest()
                                for name in names}}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
