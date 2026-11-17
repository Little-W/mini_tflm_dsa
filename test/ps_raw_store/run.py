#!/usr/bin/env python3
"""Check deterministic INT32 frame slots against an independent memory model."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--verilator',default='verilator')
    parser.add_argument('--large', action='store_true', help='Fill every data-bank word, including a 256-row frame')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [root/'test/ps_raw_store/tb.sv', root/'test/ps_raw_store/main.cpp',
               root/'rtl/npu/ps_compact/ps_frame_store.sv']
    hashes = {str(p.relative_to(root)): digest(p) for p in sources}
    command = [args.verilator, '--cc', '--exe', '--build', '--assert', '-Wno-fatal',
               '--top-module', 'ps_raw_store_tb', '--Mdir', str(out/'obj'),
               '-j', str(args.jobs), '-CFLAGS', '-std=c++20 -O1 -fsanitize=undefined',
               '-LDFLAGS', '-fsanitize=undefined', *map(str, sources)]
    if args.large:command.append('-GMAX_FRAME_ROWS=256')
    with (out/'compile.log').open('w') as log:
        subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = out/'obj/Vps_raw_store_tb'
    result = subprocess.run([str(binary), *(['large'] if args.large else [])], text=True, capture_output=True, check=True)
    (out/'run.log').write_text(result.stdout+result.stderr)
    assert 'RAW_STORE_PASS' in result.stdout
    assert all(digest(root/p) == h for p, h in hashes.items())
    summary = dict(passed=True, source_sha256=hashes, binary_sha256=digest(binary),
                   compile_command=command, result=result.stdout.strip())
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(result.stdout, end='')


if __name__ == '__main__':
    main()
