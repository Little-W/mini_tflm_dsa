#!/usr/bin/env python3
"""Exercise synchronous partial-sum frame replay and circular storage."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rtl', type=Path, default=Path(__file__).resolve().parents[2]/'rtl/npu/buffers/ps_buffer.sv')
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[2]/'build/ps_buffer_replay')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    sources = [args.rtl.resolve(), here/'top.sv', here/'main.cpp', here/'run.py',
               here.parents[1]/'rtl/common/regfile.v']
    hashes = {str(path): digest(path) for path in sources}
    records = []
    for depth, frames, length in [(7, 1, 3), (17, 3, 7), (16, 2, 7)]:
        out = args.out.resolve()/f'depth{depth}_frames{frames}'
        out.mkdir(parents=True, exist_ok=True)
        generate = [args.verilator, '--cc', '--exe', '--assert', '-Wno-fatal',
                    '--top-module', 'ps_replay_top', '--Mdir', str(out/'obj'),
                    f'-GDEPTH={depth}', f'-GFRAME_COUNT={frames}', f'-GMAX_FRAME_LEN={length}',
                    '-CFLAGS', f'-std=c++17 -DTEST_DEPTH={depth} -DTEST_FRAMES={frames} -DTEST_MAX_LEN={length}',
                    *map(str, [path for path in sources if path.suffix in ('.sv', '.v', '.cpp')])]
        compile_command = ['make', '-C', str(out/'obj'), '-f', 'Vps_replay_top.mk',
                           '-j', '1', 'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O1']
        for command, name in [(generate, 'generate.log'), (compile_command, 'compile.log')]:
            with (out/name).open('w') as stream:
                result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
            if result.returncode:
                print((out/name).read_text()[-5000:])
                return result.returncode
        binary = out/'obj/Vps_replay_top'
        run = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out/'run.log').write_text(run.stdout)
        print(run.stdout.strip(), flush=True)
        passed = run.returncode == 0 and 'PS_REPLAY_PASS' in run.stdout
        records.append(dict(passed=passed, depth=depth, frames=frames, max_frame_len=length,
                            generate_command=generate, compile_command=compile_command,
                            binary_sha256=digest(binary), returncode=run.returncode,
                            counters={key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', run.stdout)}))
        if not passed:
            break
    unchanged = hashes == {str(path): digest(path) for path in sources}
    passed = unchanged and len(records) == 3 and all(record['passed'] for record in records)
    (args.out/'summary.json').write_text(json.dumps(dict(passed=passed, source_sha256=hashes,
        sources_unchanged_during_run=unchanged, runs=records), indent=2)+'\n')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
