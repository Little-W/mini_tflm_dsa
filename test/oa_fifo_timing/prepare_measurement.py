#!/usr/bin/env python3
"""保存完整输出写回与循环 FIFO 的联合综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='b7a2af3d')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        sources = [HERE / 'oa_fifo_timing_top.sv']
        for relative in ('rtl/npu/writeback/oa_writer.sv', 'rtl/npu/writeback/vec_s8_to_fifo.sv'):
            path = out / (label + '_' + Path(relative).name)
            content = read_rtl_source(args.reference + ':' + relative, cwd=ROOT) \
                if label == 'reference' else (ROOT / relative).read_bytes()
            path.write_bytes(content)
            sources.append(path)
        hashes[label] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
        cases[label] = {'top': 'oa_fifo_timing_top',
                        'options': ['-GVLEN=16', '-GBUS_WIDTH=64', '-GCOUNT_WIDTH=28'],
                        'sources': list(map(str, sources)),
                        'configuration': 'Production writer and 32-bank cyclic S8 FIFO; all public outputs retained'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps({'reference': args.reference, 'sources_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
