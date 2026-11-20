#!/usr/bin/env python3
"""为读取首段地址比较准备共享当前依赖的参考数值测试目录。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'
DEPENDENCIES = (
    'rtl/common/regfile.v',
    'rtl/common/add_equal.sv',
    'test/linear_dma_context/linear_dma_4k_top.sv',
    'test/linear_dma_context/main.cpp',
    'test/linear_dma_context/run.py',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='38f32d93')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    content = read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT)
    source = out / SOURCE
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    for filename in DEPENDENCIES:
        destination = out / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / filename, destination)
    manifest = {
        'reference': args.reference,
        'source_sha256': {
            filename: hashlib.sha256((out / filename).read_bytes()).hexdigest()
            for filename in (SOURCE, *DEPENDENCIES)
        },
    }
    (out / 'source_manifest.json').write_text(
        json.dumps(manifest, indent=2) + '\n')
    print(out)


if __name__ == '__main__':
    main()
