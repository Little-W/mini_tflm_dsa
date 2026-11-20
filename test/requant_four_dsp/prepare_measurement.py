#!/usr/bin/env python3
"""固定完整 INT32 乘法器及生产规模量化模块的比较源码。"""
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
    parser.add_argument('--reference-rev', default='5d148afe')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    relative = 'rtl/npu/conv/vector_scalar_multiplier.sv'
    multiplier_sources = {}
    for name in ('reference', 'candidate'):
        source = out / (name + '_multiplier.sv')
        content = (subprocess.check_output(['git', 'show', args.reference_rev + ':' + relative], cwd=ROOT)
                   if name == 'reference' else (ROOT / relative).read_bytes())
        source.write_bytes(content)
        multiplier_sources[name] = source
    quant = out / 'vec_requant.sv'
    quant.write_bytes((ROOT / 'rtl/npu/writeback/vec_requant.sv').read_bytes())
    cases = {}
    for name, source in multiplier_sources.items():
        cases[name + '_multiplier'] = {
            'top': 'registered_multiplier_s32',
            'options': ['-Gp_use_dsp=1', '-Gp_input_register=1', '-Gp_b_input_register=1'],
            'sources': [str(source)],
            'configuration': 'Full signed32 product, AREG=1, BREG=1, two arithmetic enabled edges',
        }
        cases[name + '_quant'] = {
            'top': 'vec_requant',
            'options': ['-GBUS_WIDTH=64', '-GVLEN=16', '-GMAX_IA_REUSE=32', '-GENABLE_S16=1'],
            'sources': [str(quant), str(source)],
            'configuration': 'Complete production quantization with every public output retained',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    paths = [*multiplier_sources.values(), quant, ROOT / 'rtl/common/REGFILE.v']
    manifest = {'reference_revision': args.reference_rev,
                'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
