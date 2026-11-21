#!/usr/bin/env python3
"""保存采用相同外围逻辑的线性 DMA 参考模块与当前模块。"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def reference_text(current):
    marker = '        end else begin : g_next_length'
    if current.count(marker) != 1:
        raise RuntimeError('后续读长度生成区域数量不正确')
    begin = current.index(marker)
    end = current.index('\n        // 剩余拍数的减一结果提前计算', begin)
    fragment = (HERE / 'reference_next_length.sv').read_text()
    return current[:begin] + fragment + current[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = args.source_root.resolve() / SOURCE
    current = path.read_text()
    fragment = (HERE / 'reference_next_length.sv').read_text()
    reference = reference_text(current)
    (out / 'reference.sv').write_text(reference)
    (out / 'current.sv').write_text(current)
    record = dict(source_path=str(path), source_sha256=digest(current.encode()),
        reference_source_sha256=digest(reference.encode()),
        reference_fragment_sha256=digest(fragment.encode()))
    (out / 'inputs.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))


if __name__ == '__main__':
    main()
