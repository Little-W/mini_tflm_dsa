#!/usr/bin/env python3
"""保存部分和调度器列分块寄存的独立综合输入。"""
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
    parser.add_argument('--reference', default='2f06471c')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = 'rtl/npu/control/ps_window_scheduler.sv'
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        data = (read_rtl_source(f'{args.reference}:{source}', cwd=ROOT)
                if label == 'reference' else (ROOT / source).read_bytes())
        path = out / (label + '.sv')
        path.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        cases[label] = {
            'top': 'ps_window_scheduler',
            'options': ['-D', 'SYNTHESIS=1', '-GSIZE=16', '-GFRAME_COUNT=16', '-GMAX_REUSE_TILES=32'],
            'sources': [str(path)],
            'configuration': 'SIZE16, FRAME_COUNT16, MAX_REUSE_TILES32',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'input_manifest.json').write_text(json.dumps(
        {'reference': args.reference, 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
