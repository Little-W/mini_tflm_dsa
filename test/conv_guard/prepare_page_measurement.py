#!/usr/bin/env python3
"""保存读取保护器页范围计算的固定生产参数综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/conv_axi_read_guard.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='3587da43')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        content = subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)], cwd=ROOT) \
            if label == 'reference' else (ROOT / SOURCE).read_bytes()
        source = out / (label + '.sv')
        source.write_bytes(content)
        hashes[label] = hashlib.sha256(content).hexdigest()
        cases[label] = {
            'top': 'conv_axi_read_guard', 'sources': [str(source)],
            'options': ['-GADDR_W=32', '-GDATA_W=64', '-GSPLIT_GEMM_4K=1', '-GREAD_OUTSTANDING=4'],
            'configuration': '32位地址、64位数据、四笔并发读取和4KiB页拆分',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(
        {'reference': args.reference, 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
