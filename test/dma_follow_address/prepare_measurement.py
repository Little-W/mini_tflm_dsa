#!/usr/bin/env python3
"""保存线性 DMA 的参考与当前源码，生成生产参数的独立综合配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/dma/axi_linear_block_dma.sv'
COMMON = ('rtl/common/regfile.v', 'rtl/common/add_equal.sv')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='dde5e7c9')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    revision = subprocess.check_output(['git', 'rev-parse', args.baseline_ref],
                                       cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT)
    current = (ROOT / SOURCE).read_bytes()
    parameters = {'SIZE': 64, 'BUS_WIDTH': 64, 'DATA_WIDTH': 16, 'REG_WIDTH': 32,
                  'RD_CONTEXT_DEPTH': 4, 'DMA_MAX_BYTES': 2048, 'CACHE_BLOCKS': 64}
    cases = {}
    for label, contents in (('reference', reference), ('current', current)):
        target = out / 'inputs' / label / SOURCE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        cases[label] = {
            'top': 'axi_linear_block_dma', 'sources': [str(target)],
            'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                       [f'-G{key}={value}' for key, value in parameters.items()],
            'parameters': parameters,
            'configuration': '线性 DMA：生产配置，包含读取上下文与后续地址准备',
        }
    hashes = {SOURCE: digest(current)}
    for name in COMMON:
        data = (ROOT / name).read_bytes()
        target = out / 'inputs/current' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        hashes[name] = digest(data)
    manifest = {'reference_revision': revision, 'source_sha256': hashes,
                'reference_source_sha256': {SOURCE: digest(reference)},
                'parameters': parameters, 'runner_sha256': digest(Path(__file__).read_bytes())}
    (out / 'inputs.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'reference_revision': revision, 'source_sha256': hashes}))


if __name__ == '__main__':
    main()
