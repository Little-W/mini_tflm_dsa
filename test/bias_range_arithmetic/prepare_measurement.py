#!/usr/bin/env python3
"""为两份完整偏置加载器源码生成相同生产参数的综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FILES = ('rtl/npu/loaders/bias_loader.sv', 'rtl/npu/loaders/bias_loader_ctrl.sv',
         'rtl/npu/loaders/bias_loader_buffer.sv')
PARAMETERS = {'SIZE': 16, 'BUS_WIDTH': 64, 'DATA_WIDTH': 32, 'REG_WIDTH': 32,
              'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-ref', default='fe0ed2325743c9b353b74377fbe7b4a1e9d19d64')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    cases, manifest = {}, {}
    for label in ('reference', 'current'):
        paths, hashes = [], {}
        for name in FILES:
            content = (subprocess.check_output(['git', 'show', f'{args.reference_ref}:{name}'], cwd=ROOT)
                       if label == 'reference' else (args.source_root / name).read_bytes())
            path = out / label / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            paths.append(str(path))
            hashes[name] = hashlib.sha256(content).hexdigest()
        manifest[label] = hashes
        cases[label] = {'top': 'bias_loader', 'sources': paths, 'parameters': PARAMETERS,
                        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                                   [f'-G{key}={value}' for key, value in PARAMETERS.items()],
                        'configuration': '完整双银行偏置加载器'}
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
