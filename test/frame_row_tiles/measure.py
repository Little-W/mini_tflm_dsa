#!/usr/bin/env python3
"""测量帧行数寄存器经过分块数和尾组行数计算后的完整组合路径。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    loader = ROOT/'rtl/npu/loaders/ia_loader.sv'
    tail_model = runpy.run_path(str(ROOT/'test/ia_frame_rows/run_depth.py'))['tail_model']
    header = '''// 帧行数、尾组配置与数据流模式的寄存器间测量。
module measure(
 input logic clk, // 配置寄存器时钟
 input logic [31:0] rows, // 帧行数
 input logic [31:0] other_k, // 独立配置的输入行数
 input logic [31:0] configured_tiles, // 非帧模式的尾组分块数
 input logic frame_mode, // 选择帧执行模式
 input logic is_mode, // 选择输入驻留数据流
 output logic [31:0] tail // 寄存后的尾组行数
);
logic [31:0] rq,kq,tq,rounded,selected_tiles,selected_k,tc;
logic fq,mq;
always_ff @(posedge clk) begin
 rq<=rows;kq<=other_k;tq<=configured_tiles;fq<=frame_mode;mq<=is_mode;tail<=tc;
end
assign selected_k=fq?(mq?kq:rq):kq;
selected_tail u_tail(.k(selected_k),.row_tail_tiles(selected_tiles),.frame_last_rows_next(tc));
'''
    bodies = {
        'reference': "assign rounded=rq+32'd15;assign selected_tiles=fq?(rounded>>4):tq;\n",
        'current': '''logic [31:0] ceil_tiles;
npu_frame_row_tiles u_round(.i_rows(rq),.o_tiles(ceil_tiles));
assign selected_tiles=fq?ceil_tiles:tq;
'''}
    cases = {}
    for name, body in bodies.items():
        path = out/(name+'.sv')
        path.write_text(tail_model(loader.read_text(), 'selected_tail')+header+body+'endmodule\n')
        cases[name] = dict(top='measure', sources=[str(path)],
                           options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                           configuration='32 位帧行数配置到尾组行数寄存器，SIZE=16，COUNT_WIDTH=29')
    config = out/'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--case-config', config,
                    '--cases', *bodies, '--through', 'pre_lut', '--out', out/'mapping'], check=True)
    records = {}
    for name in bodies:
        folder = out/'cost'/name
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
                        '--source', out/'mapping'/name, '--out', folder, '--mode', 'physical-cost',
                        '--delay-target-ps', '6667', '--wire-delay-ps', '300', '--max-lut-inputs', '8'], check=True)
        records[name] = {item: json.loads((folder/(item+'.json')).read_text())
                         for item in ['manifest', 'metrics', 'verification']}
        records[name]['mapped_sha256'] = hashlib.sha256((folder/'mapped.json').read_bytes()).hexdigest()
    report = dict(top='measure', frame_rows_width=32, tile_size=16, frame_count_width=29,
                  loader_source_sha256=hashlib.sha256(loader.read_bytes()).hexdigest(), cases=records)
    (out/'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
