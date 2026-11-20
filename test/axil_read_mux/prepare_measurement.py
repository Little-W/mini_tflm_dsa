#!/usr/bin/env python3
"""保存 AXI-Lite 配置模块的生产参数和两份综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCE = 'rtl/axi_top/npu_axil_reg_if.sv'
PARAMETERS = {'AXI_DATA_BITS': 64, 'CONV_IS_CAPABLE': 1, 'VECTOR_ENGINE_CAPABLE': 1,
              'MATRIX_S16_BANKS': 4, 'PS_CAPS': 17825823, 'PS_POOL_BYTES': 49152,
              'IA_CACHE_BYTES': 2048, 'SHARED_TOTAL_BYTES': 57344,
              'SHARED_BANK_BYTES': 8192, 'SHARED_IA_BANK_MASK': 6,
              'PS_DIRECTORY_ROWS': 1024}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='c7088884')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    texts = {'reference': read_rtl_source(f'{args.reference}:{SOURCE}', cwd=ROOT, text=True),
             'current': (ROOT / SOURCE).read_text()}
    package = ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv'
    (out / package.name).write_bytes(package.read_bytes())
    cases = {}
    for label, text in texts.items():
        source = out / f'{label}.sv'
        source.write_text(text)
        cases[label] = {'top': 'npu_axil_reg_if',
                        'sources': [str(out / package.name), str(source)],
                        'options': ['-D', 'XILINX_FPGA=1'] +
                                   [f'-G{name}={value}' for name, value in PARAMETERS.items()],
                        'configuration': '生产 AXI-Lite 配置、完整读写接口及状态输出'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    manifest = {'reference': args.reference, 'parameters': PARAMETERS,
                'source_sha256': {name: hashlib.sha256(text.encode()).hexdigest()
                                  for name, text in texts.items()},
                'package_sha256': hashlib.sha256(package.read_bytes()).hexdigest()}
    (out / 'inputs.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
