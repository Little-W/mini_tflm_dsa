#!/usr/bin/env python3
"""保存相同公共依赖和参数下的完整帧调度器综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/control/ps_window_scheduler.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='f45a6c21')
    parser.add_argument('--dependency-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))['with_dependencies']
    sources = {'reference': subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)], cwd=ROOT),
               'current': (ROOT / SOURCE).read_bytes()}
    cases, hashes = {}, {}
    for label, data in sources.items():
        path = out / (label + '.sv'); path.write_bytes(data)
        dependencies = resolve([path], args.dependency_root.resolve())
        for dependency in dependencies:
            hashes[str(dependency)] = hashlib.sha256(dependency.read_bytes()).hexdigest()
        for name, reuse in [('production', 16), ('compact', 32)]:
            parameters = dict(SIZE=16, FRAME_COUNT=16, MAX_REUSE_TILES=reuse)
            cases[label + '_' + name] = {
                'top': 'ps_window_scheduler', 'sources': list(map(str, dependencies)),
                'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
                           [f'-G{key}={value}' for key, value in parameters.items()],
                'parameters': parameters, 'configuration': '完整帧调度器，包含全部帧进度与命令准备状态',
            }
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'manifest.json').write_text(json.dumps({'reference_revision': args.reference,
        'dependency_root': str(args.dependency_root.resolve()), 'source_sha256': hashes}, indent=2) + '\n')


if __name__ == '__main__':
    main()
