#!/usr/bin/env python3
"""证明完成阶段的等待状态不变量以及全部状态和公开输出的对应关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = Path('rtl/npu/control/ps_window_scheduler.sv')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='ef0dc75')
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--profiles', nargs='+', default=['16:16:32'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.reference_root.resolve() if args.reference_root else out / 'reference'
    if args.reference_root is None:
        (reference / RTL).parent.mkdir(parents=True, exist_ok=True)
        (reference / RTL).write_bytes(subprocess.check_output(
            ['git', 'show', f'{args.reference}:{RTL}'], cwd=ROOT))
        shutil.copytree(source / 'rtl/common', reference / 'rtl/common', dirs_exist_ok=True)
    source_hash = digest(source / RTL)
    commands = [
        ('invariant', ROOT / 'test/scheduler_pressure_state/prove_invariant.py', []),
        ('transition', ROOT / 'test/scheduler_completion/prove_transition.py',
         ['--reference-root', str(reference)]),
    ]
    reports = {}
    for name, script, extra in commands:
        destination = out / name
        with (out / f'{name}.log').open('w') as stream:
            subprocess.run([
                sys.executable, str(script), '--source-root', str(source),
                '--profiles', *args.profiles, '--out', str(destination), *extra,
            ], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
        reports[name] = json.loads((destination / 'summary.json').read_text())
        if not reports[name]['passed'] or len(reports[name]['profiles']) != len(args.profiles):
            raise RuntimeError(f'形式证明不完整: {destination}')
    if digest(source / RTL) != source_hash:
        raise RuntimeError('形式证明期间调度器源码变化')
    result = {
        'passed': True, 'source_sha256': source_hash,
        'reference_sha256': digest(reference / RTL), 'reference': args.reference,
        'external_inputs_constrained': False,
        'proof_method': 'independent reset and unbounded one-step invariant; all common state bits and public outputs',
        'reports': reports,
    }
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
