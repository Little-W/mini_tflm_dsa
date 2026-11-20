#!/usr/bin/env python3
"""固定量化商饱和实现的独立模块和完整量化综合输入。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='2f06471c')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = 'rtl/npu/writeback/vec_requant.sv'
    reference = subprocess.check_output(['git', 'show', args.reference_rev + ':' + path], cwd=ROOT)
    candidate = (ROOT / path).read_bytes()
    cases = {}
    for name, content in [('reference', reference), ('paired', candidate)]:
        source = out / (name + '.sv')
        source.write_bytes(content)
        cases[name + '_shift'] = {
            'top': 'requant_shift_pipeline',
            'options': ['-D', 'SYNTHESIS'],
            'sources': [str(source)],
            'configuration': '64-bit product, 7 enabled edges, saturating 34-bit quotient',
        }
        cases[name + '_quant'] = {
            'top': 'vec_requant',
            'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
            'sources': [str(source), str(ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv')],
            'configuration': 'Production quantization BUS64 VLEN16 reuse32 S16 and all public outputs',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    manifest = {
        'reference_rev': args.reference_rev,
        'reference_sha256': hashlib.sha256(reference).hexdigest(),
        'source_sha256': hashlib.sha256(candidate).hexdigest(),
        'dependencies_sha256': {
            name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ('rtl/npu/conv/vector_scalar_multiplier.sv', 'rtl/common/REGFILE.v')
        },
    }
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
