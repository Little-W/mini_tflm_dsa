#!/usr/bin/env python3
"""保存完整共享银行配置计算及容量常量表的测量输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run_formal import ROOT, TOP, LIMITS, allocation_module
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='087542cb')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    manifest = {'source_sha256': {str(path): hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                  for path in (TOP, LIMITS)}, 'snapshots': {}}
    for label in ('reference', 'current'):
        source = (read_rtl_source(f'{args.reference_rev}:{TOP}', cwd=ROOT, text=True)
                  if label == 'reference' else (ROOT / TOP).read_text())
        path = out / (label + '.sv')
        path.write_text(allocation_module(source))
        manifest['snapshots'][label] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases['allocation_' + label] = {
            'top': 'allocation_measure',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-DGEMMORA_PS_POOL_BYTES=49152',
                        '-Gp_total_banks=7', '-Gp_bank_bytes=8192', '-Gp_max_rows=512'],
            'parameters': {'total_banks': 7, 'bank_bytes': 8192, 'max_rows': 512},
            'sources': [str(path), str(ROOT / LIMITS)],
            'configuration': '共享银行配置寄存器、完整派生计算和部分和容量表',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
