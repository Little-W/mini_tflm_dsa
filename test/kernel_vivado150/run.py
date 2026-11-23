#!/usr/bin/env python3
"""在固定源码目录验证权重缓存的矩阵容量、发送顺序、四态行为和阵列集成。"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUFFER = Path('rtl/npu/loaders/kernel_loader_buffer.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='caace947')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--steps', nargs='+', choices=('numeric', 'four_state', 'formal', 'structure', 'array'),
                        default=['numeric', 'four_state', 'formal', 'structure', 'array'])
    parser.add_argument('--lock-file', type=Path, default=ROOT.parent / 'r20_heavy.lock')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current, reference = out / 'source/current', out / 'source/reference'
    sources = [path for folder in ('rtl/npu/loaders', 'rtl/npu/compute', 'rtl/common', 'asic/rtl')
               for path in sorted((ROOT / folder).glob('*')) if path.suffix in ('.v', '.sv', '.vh')]
    hashes = {}
    for source in sources:
        relative = source.relative_to(ROOT)
        target = current / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        hashes[str(relative)] = digest(target)
    for relative in (BUFFER, Path('rtl/common/regfile.v')):
        target = reference / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(['git', 'show', f'{args.reference}:{relative}'], cwd=ROOT))
    commands = {
        'numeric': [sys.executable, str(ROOT / 'test/kernel_row_storage/run_numeric.py'),
                    '--source-root', str(current), '--reference-root', str(reference)],
        'four_state': [sys.executable, str(ROOT / 'test/kernel_row_storage/run_four_state.py'),
                       '--source-root', str(current), '--reference-root', str(reference)],
        'formal': [sys.executable, str(ROOT / 'test/kernel_row_storage/run_partitioned.py'),
                   '--source-root', str(current), '--reference-root', str(reference), '--size', '16', '--width', '16',
                   '--reference-layout', 'parameter', '--source-layout', 'column', '--lock-file', str(args.lock_file)],
        'structure': [sys.executable, str(ROOT / 'test/kernel_asic_storage/check_structure.py'), '--source-root', str(current)],
        'array': [sys.executable, str(ROOT / 'test/kernel_prefetch/run.py'), '--source-root', str(current), '--fpga'],
    }
    reports = {}
    for stage in args.steps:
        folder = out / stage
        command = commands[stage] + ['--out', str(folder)]
        with (out / (stage + '.log')).open('w') as stream:
            if stage == 'formal':
                subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
            else:
                with args.lock_file.open('a+') as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        report = json.loads((folder / 'summary.json').read_text())
        assert report['passed'], stage
        reports[stage] = dict(summary=str(folder / 'summary.json'), sha256=digest(folder / 'summary.json'))
        for obj in folder.rglob('obj'):
            shutil.rmtree(obj)
        print(json.dumps({'stage': stage, 'passed': True}), flush=True)
    summary = dict(passed=True, reference=args.reference, source_sha256=hashes,
                   stages=reports, runner_sha256=digest(Path(__file__)),
                   worktree_matches_snapshot=all(digest(ROOT / name) == value for name, value in hashes.items()))
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
