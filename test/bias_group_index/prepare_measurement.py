#!/usr/bin/env python3
"""保存实际索引计算和完整偏置缓冲区的综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from run_formal import ROOT, TOP, BUFFER, index_block, group_start, prepare_buffer
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='bdd7109f')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    buffer = (ROOT / BUFFER).read_text()
    reference = read_rtl_source(f'{args.reference_rev}:{TOP}', cwd=ROOT, text=True)
    current = (ROOT / TOP).read_text()
    cases = {}
    manifest = {'source_sha256': {str(p): hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                   for p in (TOP, BUFFER)}, 'snapshots': {}}
    for label, top in (('reference', reference), ('current', current)):
        source = prepare_buffer(buffer, index_block(top), group_start(top))
        source = source.replace('    input logic [63:0] i_formal_read_data,\n', '')
        source = source.replace(', .i_formal_read_data(i_formal_read_data)', '')
        if 'i_formal_read_data' in source:
            raise RuntimeError('Synthesis requires the actual memory implementation')
        path = out / (label + '.sv')
        path.write_text(source)
        manifest['snapshots'][label] = hashlib.sha256(path.read_bytes()).hexdigest()
        cases['bias_index_' + label] = {
            'top': 'bias_loader_buffer',
            'options': ['-D', 'SYNTHESIS=1', '-DXILINX_FPGA=1', '-GSIZE=16',
                        '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=29', '-GGROUP_BLOCKS_MAX=32'],
            'parameters': {'SIZE': 16, 'BUS_WIDTH': 64, 'COUNT_WIDTH': 29,
                           'GROUP_BLOCKS_MAX': 32},
            'sources': [str(path)],
            'configuration': '实际顶层读索引计算与完整双银行偏置缓冲区',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
