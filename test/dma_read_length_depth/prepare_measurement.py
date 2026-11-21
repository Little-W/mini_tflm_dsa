#!/usr/bin/env python3
"""保存双通道 DMA 的两份完整测量输入，仅替换后续读长度表达式。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

from prepare_reference import reference_text

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SOURCE = Path('rtl/npu/dma/axi_linear_block_dma.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    cases = json.loads((HERE / 'cases.json').read_text())
    sources = cases['dma_length']['sources']
    for label in ('reference', 'current'):
        for name in sources:
            destination = out / label / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, destination)
    reference = out / 'reference' / SOURCE
    reference.write_text(reference_text(reference.read_text()))
    record = dict(source_sha256={label: {name: digest(out / label / name)
        for name in sources} for label in ('reference', 'current')},
        reference_fragment_sha256=digest(HERE / 'reference_next_length.sv'),
        case_configuration_sha256=digest(HERE / 'cases.json'),
        runner_sha256=digest(Path(__file__)))
    (out / 'inputs.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({label: record['source_sha256'][label][str(SOURCE)]
                      for label in ('reference', 'current')}))


if __name__ == '__main__':
    main()
