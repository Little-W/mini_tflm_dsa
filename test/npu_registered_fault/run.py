#!/usr/bin/env python3
"""在完整 NPU 功能测试中检查总线故障与配置接收。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--verilator', default='verilator-modern')
    parser.add_argument('--jobs', type=int, default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    executable = shutil.which(args.verilator)
    if not executable:
        raise RuntimeError('Verilator is unavailable')
    sources = [ROOT / 'rtl/npu/top/npu_top.sv', ROOT / 'rtl/npu/dma/axi_block_dma_arbiter.sv',
               HERE / 'observer.sv', Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in sources}
    wrapper = out / 'verilator_registered_fault'
    wrapper.write_text('#!' + sys.executable + '\nimport os,sys\ncommand=' +
                       repr([executable, str(HERE / 'observer.sv')]) +
                       '+sys.argv[1:]\nos.execv(command[0],command)\n')
    wrapper.chmod(0o755)
    command = [sys.executable, str(ROOT / 'test/compute_output_pipeline/run_npu.py'),
               '--out', str(out / 'suite'), '--verilator', str(wrapper), '--jobs', str(args.jobs)]
    with (out / 'run.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    suite = json.loads((out / 'suite/summary.json').read_text())
    coverage = []
    for path in sorted((out / 'suite').rglob('*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if line.startswith('NPU_REGISTERED_FAULT_PASS '):
                coverage.append(dict(log=str(path.relative_to(out)),
                    **{key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}))
    if not coverage or not all(sum(row[key] for row in coverage) > 0
                               for key in ('errors', 'read_errors', 'write_errors')):
        raise RuntimeError('Complete NPU verification requires both R and B error responses')
    if hashes != {str(path.relative_to(ROOT)): digest(path) for path in sources}:
        raise RuntimeError('Integration inputs changed during execution')
    result = dict(passed=suite['passed'], source_sha256=hashes, sources_unchanged=True,
                  coverage=coverage, command=command, suite_report=str(out / 'suite/summary.json'))
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(passed=result['passed'], runs=len(coverage),
                         errors=sum(row['errors'] for row in coverage))))


if __name__ == '__main__':
    main()
