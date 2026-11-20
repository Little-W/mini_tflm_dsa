#!/usr/bin/env python3
"""为实际故障组合生成一致的输入与输出寄存边界。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from extract_fault import ROOT, TOP, INPUT_BITS, measurement_source
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='47e51eff')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        source = ((ROOT / TOP).read_text() if label == 'current' else
                  read_rtl_source(f'{args.reference}:{TOP}', cwd=ROOT, text=True))
        path = out / (label + '.sv')
        path.write_text(measurement_source(source))
        hashes[label] = {'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
                         'measurement_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        cases[label] = {'top': 'fault_measure', 'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                        'sources': [str(path)],
                        'configuration': '实际顶层故障输出及 DMA 仲裁器中止连接，11 位任意输入、2 位输出'}
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps({
        'reference': args.reference, 'input_bits': INPUT_BITS, 'output_bits': 2,
        'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
