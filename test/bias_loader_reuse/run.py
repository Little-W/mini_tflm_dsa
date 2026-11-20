#!/usr/bin/env python3
"""Check bias window residency, bounded DMA reads and WS/IS data selection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    root, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = ['test/bias_loader_reuse/tb_bias_loader_reuse.sv',
             'rtl/npu/loaders/bias_loader.sv', 'rtl/npu/loaders/bias_loader_ctrl.sv',
             'rtl/npu/loaders/bias_loader_buffer.sv', 'rtl/common/regfile.v']
    sources = {name: digest(root / name) for name in names}
    command = ['verilator', '--binary', '--timing', '--assert', '-Wno-fatal',
               '--top-module', 'tb_bias_loader_reuse', '-j', str(args.jobs),
               '--Mdir', str(out / 'obj')] + [str(root / name) for name in names]
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
    result = {'passed': passed, 'case_count': len(cases), 'cases': cases,
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
