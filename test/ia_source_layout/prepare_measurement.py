#!/usr/bin/env python3
"""保存通用与生产 DMA 数据排列的同源模块综合配置。"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    parameters = dict(DATA_WIDTH=16, SIZE=16, BUS_WIDTH=64, REG_WIDTH=32,
                      CACHE_BLOCKS=32, COMPACT_S8=1,
                      RAM_WORD_ADDR_WIDTH=12, p_compact_offset_width=9)
    cases = {}
    for name, enabled in [('general', 0), ('production', 1)]:
        values = dict(parameters, p_dma_source_layout=enabled)
        cases[name] = dict(top='ia_loader_cache_mgr',
            sources=['rtl/npu/loaders/ia_loader_cache_mgr.sv', 'rtl/npu/compute/select_add.sv'],
            parameters=values, options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] +
            [f'-G{key}={value}' for key, value in values.items()],
            configuration='生产输入激活缓存，通用与专用 DMA 数据排列')
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
