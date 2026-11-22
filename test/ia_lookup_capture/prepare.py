#!/usr/bin/env python3
"""保存 IA 请求比较的参考源码和当前源码，并生成生产参数综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/loaders/ia_loader.sv')
DEPENDENCIES = (
    Path('rtl/npu/loaders/ia_loader_ctrl.sv'),
    Path('rtl/npu/loaders/ia_loader_cache_mgr.sv'),
    Path('rtl/npu/compute/select_add.sv'),
)
PARAMETERS = {
    'SIZE': 16, 'BUS_WIDTH': 64, 'DMA_LANES': 8, 'COUNT_WIDTH': 29,
    'CACHE_BLOCKS': 32, 'EXTERNAL_RAM': 1, 'ORDERED_JOB': 1,
    'RAM_WORD_ADDR_WIDTH': 12, 'p_register_dma_request': 1,
    'p_dma_source_layout': 1, 'p_shared_write_stage': 1,
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='ef0dc75')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cases, hashes = {}, {}
    for label in ('reference', 'candidate'):
        folder = out / label
        hashes[label] = {}
        for relative in (SOURCE, *DEPENDENCIES):
            target = folder / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if label == 'reference' and relative == SOURCE:
                content = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT)
            else:
                content = (source / relative).read_bytes()
            target.write_bytes(content)
            hashes[label][str(relative)] = hashlib.sha256(content).hexdigest()
        shutil.copytree(source / 'rtl/common', folder / 'rtl/common', dirs_exist_ok=True)
        cases['current' if label == 'candidate' else label] = {
            'top': 'ia_lookup_capture_measure',
            'sources': [str(folder / relative) for relative in (SOURCE, *DEPENDENCIES)] +
                       [str(ROOT / 'test/ia_lookup_capture/measure.sv')],
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                       [f'-G{name}={value}' for name, value in PARAMETERS.items()],
            'parameters': PARAMETERS,
            'configuration': '完整生产参数 IA 加载器，DMA 启动输出由测量寄存器保存',
        }
    synthesis = out / 'synthesis'
    synthesis.mkdir(exist_ok=True)
    (synthesis / 'cases.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    result = {'reference': args.reference, 'source_sha256': hashes, 'parameters': PARAMETERS}
    (out / 'sources.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
