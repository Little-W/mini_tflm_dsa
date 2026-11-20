#!/usr/bin/env python3
"""保存生产参数下的读取突发长度比较源码与综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')


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
            'top': 'axi_linear_block_dma',
            'options': ['-GSIZE=64', '-GBUS_WIDTH=64', '-GDATA_WIDTH=16',
                        '-GCACHE_BLOCKS=64', '-GRD_CONTEXT_DEPTH=4', '-GRD_TAG_WIDTH=3'],
            'sources': [str(source)],
            'configuration': '生产线性DMA，64位总线、64个槽位和4个读取上下文',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(
        {'reference': args.reference, 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
