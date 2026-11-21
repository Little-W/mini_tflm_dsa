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
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--fpga', action='store_true')
    parser.add_argument('--bus-width', type=int, choices=[32, 64], default=32)
    parser.add_argument('--read-width', type=int, choices=[32, 64, 128], default=32)
    parser.add_argument('--line-bytes', type=int, choices=[16, 32, 64, 128, 256], default=16)
    parser.add_argument('--cache-bytes', type=int,
                        help='Keep total data storage fixed while varying line size and ways')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--out', type=Path, default=ROOT / 'build/cache_pipeline')
    parser.add_argument('--profiles', nargs='+', default=['4:2', '2:2', '4:1', '1:2'])
    args = parser.parse_args()
    if args.read_width//8>args.line_bytes:
        parser.error('Read width must fit within one cache line')
    sources = [(ROOT / 'rtl/npu/dma' / name if name.startswith('cache/') else ROOT / 'rtl/npu/conv' / name) for name in
               ['cache/conv_read_cache.sv', 'cache/conv_sdp_ram.sv', 'conv_axi_span_reader.sv']]
    sources += [ROOT / 'test/conv_reuse/axi_counted_memory.sv',
                ROOT / 'test/cache_pipeline/tb_cache_pipeline.sv']
    import runpy
    sources = runpy.run_path(str(ROOT / "test/monitors/sources.py"))["with_observers"](sources)
    candidate_root = args.source_root.resolve()
    sources = [candidate_root / path.relative_to(ROOT)
               if path.is_relative_to(ROOT) and path.relative_to(ROOT).parts[0] == 'rtl' else path
               for path in sources]
    hashes = {str(path): digest(path) for path in sources + [Path(__file__)]}
    profiles = []
    for profile in args.profiles:
        depth, ways = map(int, profile.split(':'))
        sets=8 if args.cache_bytes is None else args.cache_bytes//(ways*args.line_bytes)
        if (sets<2 or sets&(sets-1) or
                (args.cache_bytes is not None and sets*ways*args.line_bytes!=args.cache_bytes)):
            parser.error('Cache capacity requires a power-of-two set count >=2')
        out = args.out / f'd{depth}_w{ways}'
        out.mkdir(parents=True, exist_ok=True)
        command = [args.verilator, '--binary', '--timing', '--assert', '-DCONV_ASSERT','-DNPU_SIM_ASSERT',
                   *(['-DXILINX_FPGA=1'] if args.fpga else []),
                   '-Wall', '-Wno-fatal', '--top-module', 'tb_cache_pipeline',
                   f'-GDEMAND_DEPTH={depth}', f'-GCACHE_WAYS={ways}',
                   f'-GCACHE_SETS={sets}', f'-GLINE_BYTES={args.line_bytes}',
                   f'-GBUS_WIDTH={args.bus_width}', f'-GREAD_WIDTH={args.read_width}',
                   '--Mdir', str(out / 'obj'), '-j', str(args.jobs),
                   '--output-groups', '0', '-CFLAGS', '-std=c++20 -O1',
                   '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
                   *map(str, sources)]
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
        profiles.append({'passed': True, 'depth': depth, 'ways': ways, 'sets': sets,
                         'cache_bytes':sets*ways*args.line_bytes,
                         'binary_sha256': digest(binary), 'hit_latency_cycles': 2 if depth > 1 else 1,
                         'result': result, 'cases': cases})
        for temporary in (out / 'obj').iterdir():
            if temporary.suffix in ('.o', '.gch'):
                temporary.unlink()
    for name, value in hashes.items():
        if digest(Path(name)) != value:
            raise RuntimeError(f'Source changed during verification: {name}')
    result = {'passed': True, 'source_sha256': hashes,
              'xilinx_fpga': args.fpga,
              'bus_width': args.bus_width, 'read_width': args.read_width, 'profiles': profiles,
              'line_bytes':args.line_bytes,
              'hit_counter_definition': 'Cache line resident at external request acceptance',
              'lookup_counter_definition': 'Cache line resident when queued request reaches lookup'}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(args.out / 'summary.json', flush=True)


if __name__ == '__main__':
    main()
