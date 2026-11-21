#!/usr/bin/env python3
"""证明完整位宽的通道地址匹配、横坐标递增和预读坐标加法。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def section(source, first, last):
    start = source.index(first)
    return source[start:source.index(last, start)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = source_root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    source = path.read_text()
    channel = '''module channel_address #(parameter int p_word_shift=3)(
input conv_im2col_pkg::conv_cfg_t c,input logic[15:0] ch_q,
input logic[31:0] group_base_addr,word_addr,input logic word_valid,
output logic equivalent);
logic[16:0] channel_byte_offset;
logic[17:0] channel_addr_low;
logic[14:0] channel_addr_high_next;
logic[31:0] channel_addr,expected_addr;
logic unused_channel_addr_carry,channel_saved_hit;
''' + section(source, '  assign channel_byte_offset =', '  // 末列判断随坐标寄存') + \
        section(source, '  // 通道地址的字命中直接比较加法等式', '  // 当前行最后一拍被接收时') + '''
assign expected_addr=group_base_addr+(32'(ch_q)<<c.input_s16);
assign equivalent=channel_addr==expected_addr && channel_saved_hit==
 (word_valid && word_addr=={expected_addr[31:p_word_shift],{p_word_shift{1'b0}}});
endmodule
'''
    increments = '''module coordinate_increment(
input logic signed[34:0] ix,pfa_x,input logic[31:0] pf_step_q,output logic equivalent);
localparam int COORD_W=35;
logic[34:0] ix_increment;
logic unused_ix_increment_carry;
''' + section(source, '  // 输入横坐标的完整三十五位增量', '  // 各种通道来源并行计算组内范围') + \
        section(source, '  // 下一预读横坐标先完成分组求和', '  // 较大通道数按缓存行预测后续像素') + '''
assign equivalent=ix_increment==35'(ix+35'd1) && prefetch_next_x==(32'(pfa_x)+pf_step_q);
endmodule
'''
    cases = [(f'channel_word{bits}', 'channel_address', channel, [f'-Gp_word_shift={bits}'])
             for bits in (2, 3, 4, 7)]
    cases.append(('coordinate_increment', 'coordinate_increment', increments, []))
    if 'history_width_reached' in source:
        history = '''module history_coordinate #(parameter bit REGISTER_DESCRIPTOR=1)(
input conv_im2col_pkg::conv_cfg_t c,input logic[15:0] last_x,p_history_delta_q,
input logic[31:0] p_decode,last_p,output logic equivalent);
logic[15:0] p_delta;
logic[16:0] p_sum,p_sum_reduced,expected_sum;
logic unused_p_sum_carry,unused_p_sum_reduced_carry;
''' + section(source, '  assign p_delta =', '  // 行尾等式直接压缩') + '''
assign expected_sum={1'b0,last_x}+{1'b0,p_delta};
assign equivalent=p_sum==expected_sum && p_sum_reduced==(expected_sum-{1'b0,c.output_w}) &&
 history_width_reached==(expected_sum>={1'b0,c.output_w});
endmodule
'''
        for registered in (0, 1):
            cases.append((f'history_coordinate_r{registered}', 'history_coordinate', history,
                          [f'-GREGISTER_DESCRIPTOR={registered}']))
    results = []
    for name, top, body, options in cases:
        test, script, log = out / (name + '.sv'), out / (name + '.ys'), out / (name + '.log')
        test.write_text(body)
        files = [source_root / 'rtl/npu/conv/conv_im2col_pkg.sv',
                 source_root / 'rtl/common/add_equal.sv',
                 source_root / 'rtl/common/parallel_prefix_add.sv', test]
        script.write_text('read_slang --top ' + top + ' ' + ' '.join(options) + ' ' +
            ' '.join(shlex.quote(str(item)) for item in files) +
            '\nprep -top ' + top + ' -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        results.append({'case': name, 'passed': True})
        print('FRONTEND_ADDRESS_PROOF_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': results,
        'input_assumptions': [],
        'frontend_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}, indent=2) + '\n')


if __name__ == '__main__':
    main()
