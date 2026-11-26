#!/usr/bin/env python3
"""Check bias window residency, bounded DMA reads and WS/IS data selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--verilator', default='verilator')
    parser.add_argument('--fpga', action='store_true')
    args = parser.parse_args()
    root, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = ['test/bias_loader_reuse/tb_bias_loader_reuse.sv',
             'rtl/npu/loaders/bias_loader.sv', 'rtl/npu/loaders/bias_loader_ctrl.sv',
             'rtl/npu/loaders/bias_loader_buffer.sv', 'rtl/common/regfile.v',
             'rtl/common/parallel_prefix_add.sv', 'rtl/common/parallel_unsigned_compare.sv',
             'rtl/common/add_equal.sv']
    resolve = runpy.run_path(str(root / 'scripts/rtl/source_files.py'))['with_dependencies']
    names = [str(path.relative_to(root)) for path in resolve([root / name for name in names], root)]
    sources = {name: digest(root / name) for name in names}
    command = [args.verilator, '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_bias_loader_reuse', '-j', str(args.jobs),
               '--output-groups', '0', '-CFLAGS', '-std=c++20 -O1',
               '-MAKEFLAGS', 'OPT_FAST=-O1 OPT_SLOW=-O0 VK_PCH_I_FAST= VK_PCH_I_SLOW= CFG_CXXFLAGS_PCH=-E',
               '--Mdir', str(out / 'obj')] + [str(root / name) for name in names]
    if args.fpga:
        command += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
    with (out / 'build.log').open('w') as log:
        build = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if build.returncode:
        raise RuntimeError(f'Bias test build failed: {out / "build.log"}')
    simulator = out / 'obj/Vtb_bias_loader_reuse'
    with (out / 'run.log').open('w') as log:
        run = subprocess.run([str(simulator)], stdout=log, stderr=subprocess.STDOUT)
    output = (out / 'run.log').read_text()
    cases = [dict((key, int(value)) for key, value in re.findall(r'(\w+)=(\d+)', line))
             for line in output.splitlines() if line.startswith('BIAS_REUSE_PASS ')]
    unchanged = sources == {name: digest(root / name) for name in names}
    passed = run.returncode == 0 and 'BIAS_LOADER_REUSE_PASS' in output and unchanged
    result = {'passed': passed, 'case_count': len(cases), 'cases': cases, 'fpga': args.fpga,
              'source_sha256': sources, 'sources_unchanged': unchanged,
              'build_command': command, 'build_returncode': build.returncode,
              'run_returncode': run.returncode,
              'simulator': str(simulator), 'simulator_sha256': digest(simulator),
              'runner_sha256': digest(Path(__file__))}
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': passed, 'case_count': len(cases),
                      'result': str(out / 'result.json')}))
    return int(not passed)


if __name__ == '__main__':
    raise SystemExit(main())
