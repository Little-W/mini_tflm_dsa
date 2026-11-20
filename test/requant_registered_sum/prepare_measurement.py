#!/usr/bin/env python3
"""固定参考量化源和生产参数，生成两个独立综合配置。"""
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
    parser.add_argument('--reference-rev', default='1c081bc')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    reference_source = read_rtl_source(f'{args.reference_rev}:{relative}', cwd=ROOT)
    reference = out / 'reference.sv'
    reference.write_bytes(reference_source)
    candidate = ROOT / relative
    cases = {}
    for label, path in [('reference', reference), ('registered_sums', candidate)]:
        cases[label] = {
            'top': 'vec_requant',
            'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
            'sources': [str(path), str(ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv')],
            'configuration': 'Production quantization BUS64 VLEN16 reuse32 per-channel IS S16 enabled',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    manifest = {'reference_rev': args.reference_rev,
                'reference_source_sha256': hashlib.sha256(reference_source).hexdigest(),
                'candidate_source_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest()}
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
