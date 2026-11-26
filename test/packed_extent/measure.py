#!/usr/bin/env python3
"""测量分块维度取整的资源和寄存器间组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = 'rtl/npu/top/npu_task_configuration.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='7eb7f3ed')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    header = '''// 分块维度取整的寄存输入和输出测量模块。
module measure(
    input logic clk, // 测量时钟
    input logic [31:0] value, // 原始矩阵维度
    input logic packed_mode, // 选择分块存储
    output logic [31:0] result // 寄存后的换算结果
);
logic [31:0] q,y;
logic pq;
always_ff @(posedge clk) begin q<=value; pq<=packed_mode; result<=y; end
'''
    (out/'reference.sv').write_text(header+"assign y=pq?32'((64'(q)+64'd16-64'd1)>>4):q;\nendmodule\n")
    (out/'current.sv').write_text(header+
        'npu_packed_extent u_extent(.i_dimension(q),.i_packed(pq),.o_extent(y));\nendmodule\n')
    (out/'task_reference.sv').write_bytes(subprocess.check_output(
        ['git', 'show', args.reference+':'+SOURCE], cwd=ROOT))
    (out/'task_current.sv').write_bytes((ROOT/SOURCE).read_bytes())
    cases = {}
    for name in ('reference', 'current', 'task_reference', 'task_current'):
        parent = name.startswith('task_')
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
        if parent:
            options += ['-DGEMMORA_PS_POOL_BYTES=12288', '-I', str(ROOT/'include')]
        cases[name] = {'top': 'npu_task_configuration' if parent else 'measure',
            'sources': [str(out/(name+'.sv'))], 'options': options,
            'configuration': '完整任务配置模块' if parent else '32 位矩阵维度的分块取整'}
    config = out/'cases.json'
    config.write_text(json.dumps(cases, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
        '--case-config', config, '--cases', *cases, '--out', out/'mapping',
        '--through', 'pre_lut'], check=True, cwd=ROOT)
    records = {}
    for name in cases:
        source, cost = out/'mapping'/name, out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
            '--source', source, '--out', cost, '--mode', 'physical-cost',
            '--delay-target-ps', '6667', '--wire-delay-ps', '300',
            '--max-lut-inputs', '8'], check=True, cwd=ROOT)
        records[name] = {
            'manifest': json.loads((cost/'manifest.json').read_text()),
            'summary': json.loads((cost/'summary.json').read_text()),
            'metrics': json.loads((cost/'metrics.json').read_text()),
            'mapped_sha256': hashlib.sha256((cost/'mapped.json').read_bytes()).hexdigest()}
    (out/'measurement.json').write_text(json.dumps({'cases': records}, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
