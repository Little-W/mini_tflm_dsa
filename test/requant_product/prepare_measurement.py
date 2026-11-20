#!/usr/bin/env python3
"""固定量化乘法比较的完整输入源和 BUS64 生产参数。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='038a095')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    old = subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT)
    reference = out / 'reference.sv'
    reference.write_bytes(old)
    shared = ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv'
    cases = {}
    for label, source in [('reference', reference), ('shared_product', ROOT / relative)]:
        cases[label] = {'top': 'vec_requant',
                        'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
                        'sources': [str(source), str(shared)],
                        'configuration': 'Production quantization BUS64 VLEN16 reuse32 S16 and all public outputs'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    sources = [ROOT / relative, shared]
    manifest = {'reference_rev': args.reference_rev, 'reference_sha256': hashlib.sha256(old).hexdigest(),
                'sources_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                                   for path in sources}}
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
