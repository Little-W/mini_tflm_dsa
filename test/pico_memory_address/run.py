#!/usr/bin/env python3
"""验证 CPU 访存地址算术推断对应的完整状态与接口行为。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/soc/picorv32_npu.v')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / SOURCE)
    parser.add_argument('--reference', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = {'current': out / 'current.v', 'reference': out / 'reference.v'}
    sources['current'].write_text(read_rtl_text(args.source))
    sources['reference'].write_bytes(subprocess.check_output(
        ['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT))
    helper = ROOT / 'test/pico_pc_arithmetic/run.py'
    spec = importlib.util.spec_from_file_location('pico_complete_cpu_formal', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = {'passed': False, 'reference_commit': args.reference,
              'source_sha256': digest(args.source),
              'reference_source_sha256': digest(sources['reference']),
              'test_source_sha256': digest(Path(__file__)),
              'formal_helper_sha256': digest(helper)}
    report['formal'] = module.formal(out / 'formal', sources)
    if digest(args.source) != report['source_sha256']:
        raise RuntimeError('验证期间源文件发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
