#!/usr/bin/env python3
"""保存量化模块及依赖源码，生成相同生产参数的独立综合案例。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/writeback/vec_requant.sv'),
           Path('rtl/npu/writeback/requant_compute_lane.sv'),
           Path('rtl/npu/writeback/requant_group_buffer.sv'),
           Path('rtl/npu/conv/vector_scalar_multiplier.sv')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='0c99ca796e8a8cdd99180bcc8f8e5085abf17bca')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    paths = SOURCES + [path.relative_to(root)
                       for path in sorted((root / 'rtl/common').glob('*'))
                       if path.suffix in ('.sv', '.v')]
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        sources = []
        hashes[label] = {}
        for relative in paths:
            target = out / 'inputs' / label / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            content = (subprocess.check_output(['git', 'show', f'{args.reference}:{relative}'],
                                               cwd=ROOT)
                       if label == 'reference' else (root / relative).read_bytes())
            target.write_bytes(content)
            sources.append(str(target))
            hashes[label][str(relative)] = hashlib.sha256(content).hexdigest()
        cases[label] = {
            'top': 'vec_requant_full', 'sources': sources,
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1', '-GBUS_WIDTH=64',
                        '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1',
                        '-Gp_compute_lanes=2', '-Gp_input_rows=512'],
            'configuration': 'Complete production quantization with two compute lanes and 512 input rows'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'sources.json').write_text(json.dumps(hashes, indent=2) + '\n')


if __name__ == '__main__':
    main()
