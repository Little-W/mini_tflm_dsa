#!/usr/bin/env python3
"""保存完整偏置加载器，仅替换银行末端加法的普通 RTL 对照。"""
import argparse
import json
from pathlib import Path
from prove import ROOT, BUFFER, HELPER, digest, arithmetic_reference

PARAMETERS = {'SIZE': 16, 'BUS_WIDTH': 64, 'DATA_WIDTH': 32, 'REG_WIDTH': 32,
              'COUNT_WIDTH': 29, 'GROUP_BLOCKS_MAX': 32}
SOURCES = ['rtl/npu/loaders/bias_loader.sv', 'rtl/npu/loaders/bias_loader_ctrl.sv', BUFFER]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    cases, records = {}, []
    for name in SOURCES:
        current = (ROOT / name).read_text()
        reference = arithmetic_reference(current) if name == BUFFER else current
        row = {'source': name}
        for label, text in [('reference', reference), ('current', current)]:
            path = out / label / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            row[label + '_sha256'] = digest(path)
        records.append(row)
    for label in ['reference', 'current']:
        cases[label] = {'top': 'bias_loader', 'parameters': PARAMETERS,
                        'options': ['-D', 'SYNTHESIS=1', '-D', 'XILINX_FPGA=1'] +
                                   [f'-G{k}={v}' for k, v in PARAMETERS.items()],
                        'sources': [str(out / label / name) for name in SOURCES],
                        'configuration': '完整双银行偏置加载器，比较银行末端地址保存路径'}
    (out / 'cases.json').write_text(json.dumps(cases, indent=2, ensure_ascii=False) + '\n')
    (out / 'inputs.json').write_text(json.dumps({'parameters': PARAMETERS, 'sources': records,
        'helper_sha256': digest(ROOT / HELPER),
        'regfile_sha256': digest(ROOT / 'rtl/common/regfile.v')}, indent=2) + '\n')
    print(out / 'cases.json')


if __name__ == '__main__':
    main()
