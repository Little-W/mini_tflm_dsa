#!/usr/bin/env python3
"""为已经通过完整状态证明的两份互连源码生成相同参数的综合案例。"""
import argparse
import hashlib
import json
from pathlib import Path


import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_current_source as read_rtl_text

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--read-overlap', type=int, choices=(0, 1), default=1)
    parser.add_argument('--write-overlap', type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    formal = args.formal.resolve()
    report = json.loads(read_rtl_text(formal / 'summary.json'))
    if not report['passed']:
        raise ValueError('完整状态证明尚未通过')
    parameters = dict(ADDR_WIDTH=32, DATA_WIDTH=64, CPU_MEM_DP=65536,
                      READ_OUTSTANDING=4, WRITE_OUTSTANDING=4,
                      p_cpu_read_overlap=args.read_overlap,
                      p_cpu_ram_write_overlap=args.write_overlap)
    cases = {}
    for label in ('reference', 'current'):
        path = formal / label / 'soc_axi_interconnect.sv'
        if hashlib.sha256(path.read_bytes()).hexdigest() != report['source_sha256'][label]:
            raise ValueError('证明源码文件发生变化：' + label)
        cases[label] = dict(top='soc_axi_interconnect', sources=[str(path)],
            options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1',
                     *[f'-G{k}={v}' for k, v in parameters.items()]],
            parameters=parameters, configuration='生产 CPU/NPU 互连的全部端口与内部状态')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
