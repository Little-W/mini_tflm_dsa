#!/usr/bin/env python3
"""执行既有分段读取数值测试及生产总线宽度的缓存协议测试。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['MAKEFLAGS'] = 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E'
    sources = [ROOT / 'rtl/npu/conv/conv_axi_span_reader.sv',
               ROOT / 'test/conv_span_handoff/main.cpp']
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    command = [args.verilator, '--cc', '--exe', '--build', '--timing', '--assert', '-DNPU_SIM_ASSERT',
               '-Wall', '-Wno-fatal', '--top-module', 'conv_axi_span_reader',
               '--Mdir', str(out / 'span_obj'), '-j', '1', '-CFLAGS', '-std=c++20',
               *map(str, sources)]
    with (out / 'span_build.log').open('w') as stream:
        subprocess.run(command, cwd=ROOT, env=env, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    warnings = [line for line in (out / 'span_build.log').read_text().splitlines()
                if line.startswith('%Warning')]
    reviewed = {'UNUSEDSIGNAL', 'UNUSEDPARAM', 'SYNCASYNCNET'}
    unexpected = [line for line in warnings
                  if line.split(':', 1)[0].removeprefix('%Warning-') not in reviewed]
    if unexpected:
        raise RuntimeError(f'Unreviewed lint diagnostics: {unexpected}')
    binary = out / 'span_obj/Vconv_axi_span_reader'
    with (out / 'span_run.log').open('w') as stream:
        subprocess.run([str(binary)], cwd=ROOT, stdout=stream,
                       stderr=subprocess.STDOUT, check=True, timeout=120)
    text = (out / 'span_run.log').read_text()
    match = re.search(r'SPAN_HANDOFF_PASS cases=(\d+) spans=(\d+) handoffs=(\d+) bytes=(\d+) errors=(\d+)', text)
    if not match or match.groups()[:3] != ('4', '452', '448'):
        raise RuntimeError('Complete span handoff result missing')
    span = dict(zip(('cases', 'spans', 'handoffs', 'bytes', 'errors'), map(int, match.groups())))
    span.update(source_sha256=hashes, command=command, warnings=warnings,
                binary_sha256=digest(binary), log_sha256=digest(out / 'span_run.log'))
    print(text, flush=True)
    for path in binary.parent.iterdir():
        if path.is_file() and path != binary:
            path.unlink()
    subprocess.run([sys.executable, str(ROOT / 'test/cache_snapshot_lookup/run_protocol.py'),
                    '--out', str(out / 'cache'), '--verilator', args.verilator],
                   cwd=ROOT, env=env, check=True)
    cache = json.loads((out / 'cache/summary.json').read_text())
    if not cache['passed'] or len(cache['profiles']) != 4:
        raise RuntimeError('Complete cache protocol result missing')
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('Source changed during verification')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True, span=span, cache=cache), indent=2) + '\n')


if __name__ == '__main__':
    main()
