#!/usr/bin/env python3
"""保存整机线性 DMA 完成判断的综合输入与配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-ref', default='2f06471c')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = 'rtl/npu/dma/axi_linear_block_dma.sv'
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        data = (read_rtl_source(f'{args.reference_ref}:{source}', cwd=ROOT)
                if label == 'reference' else (ROOT/source).read_bytes())
        path = out/(label+'.sv')
        path.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        cases[label] = {
            'top': 'axi_linear_block_dma',
            'options': ['-GSIZE=64', '-GCACHE_BLOCKS=64', '-GBUS_WIDTH=64',
                        '-GDATA_WIDTH=16', '-GRD_CONTEXT_DEPTH=4'],
            'sources': [str(path)],
            'configuration': 'SoC linear DMA, SIZE64 CACHE_BLOCKS64 BUS64 DATA16 and four contexts',
        }
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(
        {'reference_ref': args.reference_ref, 'source_sha256': hashes}, indent=2)+'\n')


if __name__ == '__main__':
    main()
