#!/usr/bin/env python3
"""保存候选字段比较及突发编码的完整加载器综合输入。"""
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
    parser.add_argument('--reference-rev', default='7254ced6')
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
        for name in ('kernel_loader.sv', 'kernel_loader_ctrl.sv', 'kernel_loader_buffer.sv'):
            relative = Path('rtl/npu/loaders')/name
            data = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else (ROOT/relative).read_bytes())
            path = folder/name
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        cases['loader_'+label] = {
            'top': 'kernel_loader',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                        '-GDATA_WIDTH=16', '-GBUS_WIDTH=64', '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29'],
            'parameters': {'SIZE': 16, 'DATA_WIDTH': 16, 'BUS_WIDTH': 64,
                           'REG_WIDTH': 32, 'COUNT_WIDTH': 29},
            'sources': sources,
            'configuration': '完整十六元素权重加载器及其控制、缓存与预取状态',
        }
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')


if __name__ == '__main__':
    main()
