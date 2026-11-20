#!/usr/bin/env python3
"""固定权重计数控制器及完整加载器的同参数综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCES = (
    'rtl/npu/loaders/kernel_loader_ctrl.sv',
    'rtl/npu/loaders/kernel_loader.sv',
    'rtl/npu/loaders/kernel_loader_buffer.sv',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2f06471c')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        paths = []
        for source in SOURCES:
            data = (subprocess.check_output(['git', 'show', f'{args.reference}:{source}'], cwd=ROOT)
                    if label == 'reference' else (ROOT / source).read_bytes())
            path = out / label / Path(source).name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            paths.append(str(path))
            hashes[str(path.relative_to(out))] = hashlib.sha256(data).hexdigest()
        common = ['-D', 'SYNTHESIS=1', '-GSIZE=16', '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29']
        cases[f'controller_{label}'] = {
            'top': 'kernel_loader_ctrl', 'options': common, 'sources': paths[:1],
            'configuration': 'SIZE=16, REG_WIDTH=32, COUNT_WIDTH=29',
        }
        cases[f'loader_{label}'] = {
            'top': 'kernel_loader',
            'options': common + ['-GDATA_WIDTH=16', '-GBUS_WIDTH=64'],
            'sources': paths,
            'configuration': 'SIZE=16, DATA_WIDTH=16, BUS_WIDTH=64, REG_WIDTH=32, COUNT_WIDTH=29',
        }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'sources.json').write_text(json.dumps({
        'reference': args.reference, 'source_sha256': hashes,
    }, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
