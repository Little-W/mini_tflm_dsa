#!/usr/bin/env python3
"""测量模式选择、偏置地址计算和帧资格在寄存器之间的组合路径。"""
from __future__ import annotations

import argparse
import hashlib
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
    cases = {}
    for variant in ('reference', 'current'):
        computation = ('assign address = base_q + (channel << 2);' if variant == 'reference' else
                       'npu_bias_execution_address #(.p_base_width(32)) u_address('
                       '.i_base(base_q), .i_channel(channel), .o_address(address));')
        wrapper = out / (variant+'.sv')
        wrapper.write_text('''// 寄存器限定同一偏置地址及模式选择表达式的测量范围。
module bias_address_path (
    input wire clk, // 测量时钟
    input wire [31:0] i_base, // 任意偏置基址
    input wire [31:0] i_column, // 权重驻留模式的执行列号
    input wire [31:0] i_row, // 输入驻留模式的执行行号
    input wire i_is_mode, // 当前数据流采用输入驻留模式
    input wire i_frame_mode, // 当前执行由帧命令控制
    input wire i_ws_final_bias, // 权重驻留在最终帧使用偏置
    input wire i_frame_final, // 当前命令为最终帧
    input wire i_frame_init, // 当前命令为初始帧
    output logic [31:0] o_address // 保存当前执行的偏置字节地址
);
    logic [31:0] base_q, column_q, row_q;
    logic is_mode_q, frame_mode_q, ws_final_bias_q, frame_final_q, frame_init_q;
    logic [31:0] channel, address, selected_address;
    always_ff @(posedge clk) begin
        base_q<=i_base; column_q<=i_column; row_q<=i_row;
        is_mode_q<=i_is_mode; frame_mode_q<=i_frame_mode;
        ws_final_bias_q<=i_ws_final_bias;
        frame_final_q<=i_frame_final; frame_init_q<=i_frame_init;
        o_address<=selected_address;
    end
    assign channel=is_mode_q?row_q:column_q;
    COMPUTATION
    assign selected_address=frame_mode_q?
        ((base_q!='0 && ((is_mode_q || ws_final_bias_q)?frame_final_q:frame_init_q))?
            address:32'd0):base_q;
endmodule
'''.replace('COMPUTATION', computation))
        cases[variant] = dict(top='bias_address_path', sources=[str(wrapper)],
                              options=['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                              configuration='32 位偏置字节地址、两种执行通道和帧资格')
    config = out / 'cases.json'
    config.write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    subprocess.run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py',
                    '--case-config', config, '--cases', *cases, '--out', out/'pre',
                    '--through', 'pre_lut'], cwd=ROOT, check=True)
    rows = {}
    for variant in cases:
        target = out/'cost'/variant
        subprocess.run([sys.executable, ROOT/'scripts/fpga/remap_fpga_luts.py',
                        '--source', out/'pre'/variant, '--out', target,
                        '--mode', 'physical-cost', '--delay-target-ps', '6667',
                        '--wire-delay-ps', '300', '--max-lut-inputs', '8',
                        '--discard-abc9-temporaries'], cwd=ROOT, check=True)
        summary = json.loads((target/'summary.json').read_text())
        rows[variant] = dict(summary=summary,
                             manifest=json.loads((target/'manifest.json').read_text()),
                             paths=json.loads((target/'metrics.json').read_text())['paths'],
                             wrapper_sha256=hashlib.sha256((out/(variant+'.sv')).read_bytes()).hexdigest())
        print(variant, summary['resources']['logic_lut_cells'],
              summary['longest_register_path_cells'], flush=True)
    report = dict(scope='Registered mode selection, execution bias address and frame qualification',
                  base_width=32, channel_width=32, cases=rows)
    (out/'measurement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
