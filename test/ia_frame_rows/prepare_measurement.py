#!/usr/bin/env python3
"""保存完整 IA 加载器的参考与当前综合源码。"""
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
    parser.add_argument('--reference-rev', default='a0e01073')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases = {}
    hashes = {}
    for label in ('reference', 'current'):
        folder = out/label
        folder.mkdir(exist_ok=True)
        sources = []
        hashes[label] = {}
        for name in ('ia_loader', 'ia_loader_ctrl', 'ia_loader_cache_mgr'):
            relative = Path('rtl/npu/loaders')/(name+'.sv')
            data = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else (ROOT/relative).read_bytes())
            path = folder/relative.name
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        cases['loader_'+label] = {
            'top': 'ia_loader',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16', '-GBUS_WIDTH=64',
                        '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29', '-GCACHE_BLOCKS=32',
                        '-GEXTERNAL_RAM=1', '-GORDERED_JOB=1'],
            'parameters': {'SIZE': 16, 'BUS_WIDTH': 64, 'REG_WIDTH': 32, 'COUNT_WIDTH': 29,
                           'CACHE_BLOCKS': 32, 'EXTERNAL_RAM': 1, 'ORDERED_JOB': 1},
            'sources': sources,
            'configuration': '完整 IA 加载器，包含配置、缓存控制、预取和数据排列，外部共享 RAM',
        }
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')


if __name__ == '__main__':
    main()
