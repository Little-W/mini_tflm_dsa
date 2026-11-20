#!/usr/bin/env python3
"""保存 WS 参数写入结构比较所用的源码和生产量化配置。"""
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
    parser.add_argument('--reference-rev', default='369a3ab')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = 'rtl/npu/writeback/vec_requant.sv'
    scalar = 'rtl/npu/conv/vector_scalar_multiplier.sv'
    common = 'rtl/common/regfile.v'
    sources = {'reference': read_rtl_source(args.reference_rev + ':' + source, cwd=ROOT),
               'bank_write': (ROOT / source).read_bytes()}
    cases = {}
    for name, content in sources.items():
        path = out / (name + '.sv')
        path.write_bytes(content)
        cases[name] = {'top': 'vec_requant',
                       'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
                       'sources': [str(path), str(ROOT / scalar)],
                       'configuration': 'Production quantization BUS64 VLEN16 reuse32 S16 and all public outputs'}
    manifest = {'reference_rev': args.reference_rev,
                'reference_sha256': hashlib.sha256(sources['reference']).hexdigest(),
                'source_sha256': hashlib.sha256(sources['bank_write']).hexdigest(),
                'dependencies_sha256': {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
                                       for relative in (scalar, common)}}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
