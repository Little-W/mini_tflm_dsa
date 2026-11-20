#!/usr/bin/env python3
"""保存生产参数下的完整偏置组状态和索引综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from extract_control import ROOT, TOP, module_source
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='e5ae51f1')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference + ':' + str(TOP), cwd=ROOT, text=True)
    current = (ROOT / TOP).read_text()
    cases, hashes = {}, {}
    for label, content in [('reference', reference), ('current', current)]:
        source = out / (label + '.sv')
        source.write_text(module_source(content))
        hashes[label] = {
            'top_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'snapshot_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        cases[label] = {
            'top': 'bias_row_control',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1',
                        '-GSIZE=16', '-GREG_WIDTH=32', '-GBIAS_GROUP_BLOCKS_MAX=32'],
            'sources': [str(source)],
            'configuration': '实际NPU偏置组全部状态和行索引，16行阵列、32个分块容量',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(
        {'reference': args.reference, 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
