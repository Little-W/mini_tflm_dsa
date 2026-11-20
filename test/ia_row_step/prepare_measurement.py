#!/usr/bin/env python3
"""保存生产 IA 控制器的行步长选择综合输入。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/loaders/ia_loader_ctrl.sv'
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='eeac204b')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                      COUNT_WIDTH=29, CACHE_BLOCKS=32, COMPACT_S8=1,
                      PS_FRAME_COUNT=16, p_precomputed_packed_tiles=1,
                      p_precomputed_frame_rows=1)
    cases = {}
    for name in ('reference', 'current'):
        data = (read_rtl_source(args.reference + ':' + SOURCE, cwd=ROOT)
                if name == 'reference' else (ROOT / SOURCE).read_bytes())
        path = out / (name + '.sv')
        path.write_bytes(data)
        cases[name] = dict(top='ia_loader_ctrl', sources=[str(path)],
            parameters=parameters,
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
            [f'-G{key}={value}' for key, value in parameters.items()],
            configuration='生产 IA 控制器配置行步长选择')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
