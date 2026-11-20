#!/usr/bin/env python3
"""固定归约单元和完整向量引擎的资源比较输入。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='90ac3639')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    formal = out / 'formal'
    subprocess.run([sys.executable, str(ROOT / 'test/vector_reduce_dsp/run_formal.py'),
                    '--out', str(formal), '--reference', args.reference], cwd=ROOT, check=True)
    reference = out / 'reference'
    reference.mkdir(exist_ok=True)
    for name in ('vector_engine.sv', 'vector_pe.sv'):
        (reference / name).write_bytes(subprocess.check_output(
            ['git', 'show', f'{args.reference}:rtl/npu/conv/{name}'], cwd=ROOT))
    names = ['conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_config_check.sv',
             'vector_writeback.sv', 'vector_round_shift.sv', 'vector_scalar_multiplier.sv',
             'vector_pe.sv', 'vector_softmax.sv', 'vector_quant_params.sv', 'vector_engine.sv']
    cases = {}
    for label in ('reference', 'current'):
        sources = [str(reference / name) if label == 'reference' and name in
                   ('vector_engine.sv', 'vector_pe.sv') else 'rtl/npu/conv/' + name for name in names]
        cases['vector_' + label] = {
            'top': 'vector_engine', 'options': ['-D', 'SYNTHESIS=1', '-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
            'sources': sources, 'configuration': 'TILE16, BUS64, 8 vector PEs'}
        cases['reduce_' + label] = {
            'top': 'reduce_' + label, 'options': ['-D', 'SYNTHESIS=1'],
            'sources': ['rtl/npu/conv/conv_im2col_pkg.sv', 'rtl/npu/conv/vector_engine_pkg.sv',
                        'rtl/npu/conv/vector_pe.sv', str(formal / 'reduce_sections.sv')],
            'configuration': 'arbitrary INT32 operands, all vector operation codes'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
