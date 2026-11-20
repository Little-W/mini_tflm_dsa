#!/usr/bin/env python3
"""固定尾部通道、行数的参考源码和生产量化配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='2e17beb')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/writeback/vec_requant.sv'
    scalar = 'rtl/npu/conv/vector_scalar_multiplier.sv'
    sources = {'reference': subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT),
               'tail_count': (ROOT / relative).read_bytes()}
    cases = {}
    for name, content in sources.items():
        path = out / (name + '.sv')
        path.write_bytes(content)
        cases[name] = {'top': 'vec_requant',
                       'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
                       'sources': [str(path), str(ROOT / scalar)],
                       'configuration': 'Production quantization BUS64 VLEN16 reuse32 S16 and all public outputs'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    manifest = {'reference_rev': args.reference_rev,
                'reference_sha256': hashlib.sha256(sources['reference']).hexdigest(),
                'source_sha256': hashlib.sha256(sources['tail_count']).hexdigest(),
                'dependencies_sha256': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                                       for name in (scalar, 'rtl/common/REGFILE.v')}}
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
