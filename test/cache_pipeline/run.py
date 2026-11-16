#!/usr/bin/env python3
"""Verify ordered outstanding requests and synchronous shared-cache responses."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--verilator', default=shutil.which('verilator') or 'verilator')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/cache_pipeline')
    parser.add_argument('--profiles', nargs='+', default=['4:2', '4:1', '1:2'])
    args = parser.parse_args()
    sources = [ROOT / 'rtl/npu/conv' / name for name in
               ['conv_read_cache.sv', 'conv_sdp_ram.sv', 'conv_axi_span_reader.sv']]
    sources += [ROOT / 'test/conv_reuse/axi_counted_memory.sv',
                ROOT / 'test/cache_pipeline/tb_cache_pipeline.sv']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources + [Path(__file__)]}
    profiles = []
    for profile in args.profiles:
        depth, ways = map(int, profile.split(':'))
        out = args.out / f'd{depth}_w{ways}'
        out.mkdir(parents=True, exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-DCONV_ASSERT',
                   '-Wall', '-Wno-fatal', '--top-module', 'tb_cache_pipeline',
                   f'-GDEMAND_DEPTH={depth}', f'-GCACHE_WAYS={ways}',
                   '--Mdir', str(out / 'obj'), '-j', str(args.jobs), *map(str, sources)]
        with (out / 'build.log').open('w') as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        warnings = [line for line in (out / 'build.log').read_text().splitlines()
                    if line.startswith('%Warning')]
        reviewed = {'UNUSEDSIGNAL', 'UNUSEDPARAM', 'BLKSEQ', 'PROCASSINIT', 'SYNCASYNCNET'}
        if depth == 1:
            reviewed.add('CMPCONST')
        unexpected = [line for line in warnings
                      if line.split(':', 1)[0].removeprefix('%Warning-') not in reviewed]
        if unexpected:
            raise RuntimeError(f'Unreviewed diagnostics: {unexpected}')
        binary = out / 'obj/Vtb_cache_pipeline'
        with (out / 'run.log').open('w') as log:
            subprocess.run([str(binary)], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=120)
        text = (out / 'run.log').read_text()
        cases = []
        result = None
        for line in text.splitlines():
            if line.startswith(('CACHE_PIPELINE_CASE ', 'CACHE_PIPELINE_PASS ')):
                fields = dict(re.findall(r'(\w+)=([^ ]+)', line))
                row = {key: value if key == 'name' else int(value) for key, value in fields.items()}
                if line.startswith('CACHE_PIPELINE_CASE '):
                    cases.append(row)
                else:
                    result = row
                print(line, flush=True)
        if result is None or len(cases) != 12:
            raise RuntimeError('Incomplete RTL scenarios')
        profiles.append({'passed': True, 'depth': depth, 'ways': ways,
                         'binary_sha256': digest(binary), 'result': result, 'cases': cases})
    for name, value in hashes.items():
        if digest(ROOT / name) != value:
            raise RuntimeError(f'Source changed during verification: {name}')
    result = {'passed': True, 'source_sha256': hashes, 'profiles': profiles,
              'hit_counter_definition': 'Cache line resident at external request acceptance',
              'lookup_counter_definition': 'Cache line resident when queued request reaches lookup'}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(args.out / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
