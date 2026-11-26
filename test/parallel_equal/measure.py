#!/usr/bin/env python3
"""测量权重预测完整坐标比较及末级使能的组合路径。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''// 权重预测坐标和使能的寄存输入输出测量模块。
module measure(
    input logic clk, // 测量时钟
    input logic [63:0] a, // 第一组列和归约坐标
    input logic [63:0] b, // 第二组列和归约坐标
    input logic [3:0] enable, // 当前帧与预测结果的有效条件
    output logic start // 寄存后的预测接收事件
);
logic [63:0] aq,bq;
logic [3:0] eq;
logic start_comb;
always_ff @(posedge clk) begin aq<=a; bq<=b; eq<=enable; start<=start_comb; end
'''
    bodies = {
        'reference': 'assign start_comb=(&eq)&&(aq[63:32]!=bq[63:32]||aq[31:0]!=bq[31:0]);\n',
        'current': 'wire same; parallel_equal #(.p_width(64)) u_equal(.i_a(aq),.i_b(bq),.o_equal(same));\nassign start_comb=(&eq)&&!same;\n'}
    cases = {}
    for name, body in bodies.items():
        source = out/(name+'.sv')
        source.write_text(header+body+'endmodule\n')
        cases[name] = {'top': 'measure', 'sources': [str(source)],
            'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
            'configuration': '两组 32 位权重预测坐标与四个有效条件'}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', config, '--cases', *bodies, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name in bodies:
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300',
            '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        records[name] = {key: json.loads((cost/(key+'.json')).read_text())
                        for key in ('manifest', 'summary', 'metrics')}
    (out/'measurement.json').write_text(json.dumps({'cases': records}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
