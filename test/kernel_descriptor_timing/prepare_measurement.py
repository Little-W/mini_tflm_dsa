#!/usr/bin/env python3
"""保存权重描述符比较所用的源码与生产配置。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [Path('rtl/npu/loaders/kernel_loader_ctrl.sv'), Path('rtl/npu/loaders/kernel_loader.sv')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-rev', default='7598ae9')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    dependencies = [ROOT / 'rtl/npu/loaders/kernel_loader_buffer.sv']
    cases = {}
    source_hashes = {}
    for label in ('reference', 'current'):
        folder = out / label
        folder.mkdir(exist_ok=True)
        paths = []
        source_hashes[label] = {}
        for source in SOURCES:
            data = (subprocess.check_output(['git', 'show', f'{args.reference_rev}:{source}'], cwd=ROOT)
                    if label == 'reference' else (ROOT / source).read_bytes())
            path = folder / source.name
            path.write_bytes(data)
            paths.append(str(path))
            source_hashes[label][str(source)] = hashlib.sha256(data).hexdigest()
        cases[f'ctrl_{label}'] = {
            'top': 'kernel_loader_ctrl',
            'options': ['-GSIZE=16', '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29'],
            'sources': paths[:1],
            'configuration': 'Production weight traversal controller, SIZE16 and COUNT_WIDTH29',
        }
        cases[f'loader_{label}'] = {
            'top': 'kernel_loader',
            'options': ['-GSIZE=16', '-GDATA_WIDTH=16', '-GBUS_WIDTH=64',
                        '-GREG_WIDTH=32', '-GCOUNT_WIDTH=29'],
            'sources': paths + [str(item) for item in dependencies],
            'configuration': 'Production weight loader, SIZE16 BUS64 DATA16 COUNT_WIDTH29',
        }
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')
    report = {
        'reference_rev': args.reference_rev,
        'source_sha256': source_hashes,
        'dependency_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in dependencies + [ROOT / 'rtl/common/REGFILE.v',
                                                          ROOT / 'rtl/common/add_equal.sv',
                                                          ROOT / 'rtl/common/add3_equal.sv']},
    }
    (out / 'input_manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
