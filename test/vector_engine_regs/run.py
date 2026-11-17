#!/usr/bin/env python3
"""Verify Vector Compute Engine registers, byte writes and task exclusion."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/vector_engine_regs')
    parser.add_argument('--capable', type=int, choices=[0, 1], default=1)
    parser.add_argument('--pool-max-taps', type=int, default=256)
    parser.add_argument('--legacy-parameters', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv',
               ROOT / 'rtl/axi_top/npu_axil_reg_if.sv',
               ROOT / 'test/vector_engine_regs/tb_vector_engine_regs.sv']
    dependencies = sources + [Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    cmd = [args.verilator, '--cc', '--exe', '--main', '--timing', '--assert', '-Wno-fatal',
           '--top-module', 'tb_vector_engine_regs', '--Mdir', str(out / 'obj'),
           '--output-groups', '0', '--output-split', '12000',
           '-CFLAGS', '-std=c++17 --param=ggc-min-expand=5 --param=ggc-min-heapsize=4096',
           f'-GCAPABLE={args.capable}', f'-GPOOL_LIMIT={args.pool_max_taps}',
           *(['-DVECTOR_REGS_LEGACY_PARAMETERS'] if args.legacy_parameters else []),
           *[str(p) for p in sources]]
    make_cmd = ['make', '-C', str(out / 'obj'), '-f', 'Vtb_vector_engine_regs.mk', '-j', '1',
                'OPT_FAST=-O0', 'OPT_SLOW=-O0', 'OPT_GLOBAL=-O0',
                'VK_PCH_I_FAST=', 'VK_PCH_I_SLOW=', 'CFG_CXXFLAGS_PCH=-E']
    with (out / 'build.log').open('w') as stream:
        stream.write('COMMAND: ' + shlex.join(cmd) + '\n'); stream.flush()
        build = subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT)
        if build.returncode == 0:
            stream.write('COMMAND: ' + shlex.join(make_cmd) + '\n'); stream.flush()
            build = subprocess.run(make_cmd, stdout=stream, stderr=subprocess.STDOUT)
    if build.returncode:
        print((out / 'build.log').read_text()[-8000:])
        return build.returncode
    run = subprocess.run([str(out / 'obj/Vtb_vector_engine_regs')],
                         text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / 'run.log').write_text(run.stdout)
    unchanged = hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in dependencies}
    passed = run.returncode == 0 and 'VECTOR_ENGINE_REGS_PASS' in run.stdout and unchanged
    (out / 'summary.json').write_text(json.dumps({
        'passed': passed, 'returncode': run.returncode,
        'capable': args.capable, 'pool_max_taps': args.pool_max_taps,
        'legacy_parameters': args.legacy_parameters,
        'source_sha256': hashes, 'sources_unchanged_during_build': unchanged,
        'binary_sha256': hashlib.sha256((out / 'obj/Vtb_vector_engine_regs').read_bytes()).hexdigest(),
        'build_command': cmd, 'make_command': make_cmd,
        'result': run.stdout.strip()}, indent=2) + '\n')
    print(run.stdout)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
