#!/usr/bin/env python3
"""保存生产参数的完整偏置加载器和同步存储，供普通 RTL 映射。"""
import argparse
import json
from pathlib import Path
from common import REFERENCE, SOURCES, PARAMETERS, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    inputs = snapshot(out, args.reference)
    cases = {label: {'top': 'bias_loader',
                     'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                                [f'-G{key}={value}' for key, value in PARAMETERS.items()],
                     'sources': [str(out / label / name) for name in SOURCES],
                     'configuration': '完整双银行偏置加载器，保留 32 个分块、WS/IS 读取及 DMA 控制'}
             for label in ['reference', 'current']}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    (out / 'inputs.json').write_text(json.dumps({**inputs, 'parameters': PARAMETERS}, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
