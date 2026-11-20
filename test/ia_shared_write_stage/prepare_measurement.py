#!/usr/bin/env python3
"""生成共享写数据寄存方案的联合综合和物理比较输入。"""
import argparse
import json
from pathlib import Path

from helpers import ROOT, SOURCES, make_wrapper, make_physical_context


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper, context = out / 'cache_shared.sv', out / 'physical_context.sv'
    ports = make_wrapper(wrapper)
    make_physical_context(context, ports)
    for physical in (False, True):
        cases = {}
        for name, enabled in [('reference', 0), ('registered', 1)]:
            cases[name] = dict(top='physical_context' if physical else 'cache_shared',
                sources=([str(context)] if physical else []) + [str(wrapper), *SOURCES],
                parameters={'p_shared_write_stage': enabled},
                options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1', f'-Gp_shared_write_stage={enabled}'],
                configuration='相同输入输出寄存结构中的生产缓存与共享存储' if physical else
                              '生产 IA 缓存与七块共享存储，独立部分和通道')
        (out / ('physical_cases.json' if physical else 'cases.json')).write_text(
            json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    (out / 'physical.xdc').write_text('''create_clock -name clk -period 6.666666667 [get_ports clk]
set_property PACKAGE_PIN R4 [get_ports clk]
set_property IOSTANDARD LVCMOS15 [get_ports clk]
set_property PACKAGE_PIN E14 [get_ports serial_in]
set_property IOSTANDARD LVCMOS33 [get_ports serial_in]
set_property PACKAGE_PIN D17 [get_ports serial_out]
set_property IOSTANDARD LVCMOS33 [get_ports serial_out]
''')


if __name__ == '__main__':
    main()
