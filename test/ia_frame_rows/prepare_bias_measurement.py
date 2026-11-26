#!/usr/bin/env python3
"""导出实际矩阵引擎偏置资格表达式及相同寄存器边界的综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

from run_bias_presence import model

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/top/npu_matrix_engine.sv')

WRAPPER = '''
// 在输入与输出两侧保存生产偏置资格表达式的信号，统计组合级数。
module bias_nonzero_path (
 input logic clk, // 测量寄存器时钟
 input logic [31:0] i_base, // 任意偏置首地址
 input logic [31:0] i_channel, // 任意当前帧通道
 input logic [3:0] i_flags, // 帧执行及首末帧控制
 output logic [31:0] o_bias_present // 已保存的控制器偏置资格
);
 logic [31:0] base_q,channel_q,present;
 logic [3:0] flags_q;
 logic [1:0] unused_flags;
 always_ff @(posedge clk) begin
  base_q<=i_base;channel_q<=i_channel;flags_q<=i_flags;o_bias_present<=present;
 end
 bias_predicate u_predicate(
  .i_bias_base(base_q),.exec_channel(channel_q),.o_frame_mode_q(flags_q[3]),
  .o_is_mode(flags_q[2]),.ws_final_bias(!flags_q[2]),.frame_exec_final(flags_q[1]),
  .frame_exec_init(flags_q[0]),.controller_i_bias_base(present),.address_flags(unused_flags)
 );
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='f45a6c21')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', args.reference + ':' + str(SOURCE)],
                                        cwd=ROOT, text=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    cases, hashes = {}, {}
    for label, source in [('reference', reference), ('current', (ROOT/SOURCE).read_text())]:
        path = out/(label + '.sv')
        path.write_text(model(source, 'bias_predicate') + WRAPPER)
        sources = resolve([path], ROOT)
        for dependency in sources:
            hashes[str(dependency)] = hashlib.sha256(dependency.read_bytes()).hexdigest()
        cases[label] = {'top': 'bias_nonzero_path', 'sources': list(map(str, sources)),
                        'options': ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'],
                        'configuration': '相同寄存器边界的实际生产偏置资格表达式'}
    (out/'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2)+'\n')
    (out/'manifest.json').write_text(json.dumps({'reference_revision': args.reference,
        'source_sha256': hashes}, indent=2)+'\n')


if __name__ == '__main__':
    main()
