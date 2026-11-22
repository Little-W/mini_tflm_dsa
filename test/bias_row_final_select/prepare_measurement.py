#!/usr/bin/env python3
"""保存生产参数下的完整偏置组状态和索引综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from extract_control import ROOT, DEFAULT_REFERENCE, module_source, read_control_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=DEFAULT_REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference_path, reference = read_control_source(reference=args.reference)
    current_path, current = read_control_source()
    cases, hashes = {}, {}
    for label, content in [('reference', reference), ('current', current)]:
        source = out / (label + '.sv')
        source.write_text(module_source(content))
        hashes[label] = {
            'source_path': str(reference_path if label == 'reference' else current_path),
            'top_sha256': hashlib.sha256(content.encode()).hexdigest(),
            'snapshot_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        }
        cases[label] = {
            'top': 'bias_row_control',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1',
                        '-GSIZE=16', '-GREG_WIDTH=32', '-GBIAS_GROUP_BLOCKS_MAX=32'],
            'sources': [str(source), str(ROOT / 'rtl/common/unsigned_compare.sv')],
            'configuration': '实际NPU偏置组全部状态和行索引，16行阵列、32个分块容量',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(
        {'reference': args.reference, 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
