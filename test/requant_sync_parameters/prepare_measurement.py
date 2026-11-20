#!/usr/bin/env python3
"""固定同步量化参数实现的完整模块综合输入。"""
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
    parser.add_argument('--reference-rev', default='4ae43ade')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relatives = ('rtl/npu/writeback/vec_requant.sv',
                 'rtl/npu/conv/vector_scalar_multiplier.sv')
    hashes = {}
    cases = {}
    for label in ('reference', 'candidate'):
        sources = []
        hashes[label] = {}
        for relative in relatives:
            data = (subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT)
                    if label == 'reference' else (ROOT / relative).read_bytes())
            path = out / (label + '_' + Path(relative).name)
            path.write_bytes(data)
            sources.append(str(path))
            hashes[label][relative] = hashlib.sha256(data).hexdigest()
        cases[label] = {
            'top': 'vec_requant',
            'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
            'sources': sources,
            'configuration': 'Production quantization BUS64 VLEN16 reuse32 S16 and all public outputs',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    manifest = {'reference_revision': args.reference_rev, 'sources_sha256': hashes,
                'dependencies_sha256': {'rtl/common/REGFILE.v': hashlib.sha256(
                    (ROOT / 'rtl/common/REGFILE.v').read_bytes()).hexdigest()}}
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
