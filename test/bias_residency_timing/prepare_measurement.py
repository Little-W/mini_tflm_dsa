#!/usr/bin/env python3
"""保存偏置加载器驻留判断的完整模块综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='aa0a169c')
    parser.add_argument('--source-root', type=Path, default=ROOT)
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
        for name in ('bias_loader.sv', 'bias_loader_ctrl.sv', 'bias_loader_buffer.sv'):
            relative = Path('rtl/npu/loaders')/name
            data = (read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
                    if label == 'reference' else (args.source_root/relative).read_bytes())
            path = folder/name
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][str(relative)] = hashlib.sha256(data).hexdigest()
        cases['loader_'+label] = {
            'top': 'bias_loader',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                        '-GDATA_WIDTH=32', '-GBUS_WIDTH=64', '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29', '-GGROUP_BLOCKS_MAX=32'],
            'parameters': {'SIZE': 16, 'DATA_WIDTH': 32, 'BUS_WIDTH': 64,
                           'REG_WIDTH': 32, 'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32},
            'sources': sources,
            'configuration': '完整十六元素偏置加载器，包含两个银行与三十二分块组容量',
        }
    # 公共模块与加载器一起保存，使后续映射读取固定源码。
    shutil.copytree(args.source_root / 'rtl/common', out / 'current/rtl/common', dirs_exist_ok=True)
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'input_manifest.json').write_text(json.dumps(hashes, indent=2)+'\n')


if __name__ == '__main__':
    main()
