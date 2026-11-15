#!/usr/bin/env python3
"""Verify the shared 16-bit PE multiplier and exact 32-bit product assembly."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def run(command, log):
    with log.open('w') as stream:
        stream.write('$ ' + ' '.join(map(str, command)) + '\n')
        stream.flush()
        completed = subprocess.run(list(map(str, command)), cwd=ROOT,
                                   stdout=stream, stderr=subprocess.STDOUT)
    if completed.returncode:
        raise RuntimeError(log.read_text()[-12000:])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/vector_pe')
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    folder = args.out.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'rtl/npu/conv/vector_pe.sv', HERE / 'pe_main.cpp', Path(__file__)]
    identity = {str(src.relative_to(ROOT)): hashlib.sha256(src.read_bytes()).hexdigest() for src in sources}
    run([args.verilator, '--cc', '--exe', '--assert', '--top-module', 'vector_pe',
         '--Mdir', folder / 'obj', '-Wno-fatal', '--output-groups', '0',
         '-CFLAGS', '-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
         sources[0], sources[1]], folder / 'verilate.log')
    run(['make', '-C', folder / 'obj', '-f', 'Vvector_pe.mk', '-j', args.jobs,
         'OPT_FAST=-O1', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O1', 'VK_PCH_I_FAST=',
         'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E'], folder / 'build.log')
    if any(hashlib.sha256((ROOT / src).read_bytes()).hexdigest() != digest for src, digest in identity.items()):
        raise RuntimeError('Source identity changed during compilation')
    executable = folder / 'obj/Vvector_pe'
    run([executable], folder / 'functional.log')
    output = (folder / 'functional.log').read_text()
    match = re.search(r'VECTOR_PE_PASS comparisons=(\d+) full_products=(\d+)', output)
    if not match:
        raise RuntimeError('Verification result is incomplete')
    summary = {'passed': True, 'multipliers_per_pe': 1, 'multiplier_input_bits': 16,
               'comparisons': int(match[1]), 'full_products': int(match[2]),
               'source_sha256': identity,
               'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
               'verilator': subprocess.check_output([args.verilator, '--version'], text=True).strip()}
    (folder / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(output, end='')

if __name__ == '__main__':
    main()
