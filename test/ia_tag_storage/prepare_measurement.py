#!/usr/bin/env python3
"""保存双读取端口 IA 标签存储的参考与当前综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/ia_loader.sv'
DEPENDENCIES = ['rtl/npu/loaders/ia_loader_ctrl.sv',
                'rtl/npu/loaders/ia_loader_cache_mgr.sv',
                'rtl/npu/compute/select_add.sv']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='f0f83e1d')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(SIZE=16, BUS_WIDTH=64, COUNT_WIDTH=29, CACHE_BLOCKS=32,
                      EXTERNAL_RAM=1, ORDERED_JOB=1, RAM_WORD_ADDR_WIDTH=12,
                      PS_FRAME_COUNT=16)
    cases, hashes = {}, {}
    for label in ('reference', 'current'):
        data = (read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT)
                if label == 'reference' else (ROOT / SOURCE).read_bytes())
        snapshot = out / (label + '.sv')
        snapshot.write_bytes(data)
        hashes[label] = hashlib.sha256(data).hexdigest()
        cases[label] = dict(top='ia_loader', sources=[str(snapshot), *DEPENDENCIES],
            parameters=parameters, options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
            [f'-G{name}={value}' for name, value in parameters.items()],
            configuration='生产 IA 加载器，双同步读取端口标签存储')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    manifest = dict(reference_commit=subprocess.check_output(
        ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        parameters=parameters, source_sha256=hashes,
        common_dependency_sha256={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                  for path in DEPENDENCIES})
    (out / 'input_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
