#!/usr/bin/env python3
"""证明连续请求的缓存字地址及剩余元素判断。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = 'rtl/npu/conv/conv_im2col_frontend.sv'


def section(source, first, last):
    begin = source.index(first)
    return source[begin:source.index(last, begin)]


def unit(source):
    declarations = '''module stream_comparison #(
parameter int SIZE=16,LANES=8,p_word_shift=3,NARROW_LANES=8,
parameter int TILE_COUNT_W=$clog2(SIZE+1),CHUNK_COUNT_W=$clog2(LANES+1),
parameter int p_cache_read_bytes=1<<p_word_shift)(
input conv_im2col_pkg::conv_cfg_t c,
input logic[31:0] addr,word_addr,input logic word_valid,waiting,
input logic narrow_output,past_active_q,input logic[15:0] ch_q,
input logic[TILE_COUNT_W-1:0] col_remaining,active_remaining,
input logic[LANES-1:0] group_lane_allowed,output logic equivalent);
localparam logic[21:0] STREAM=22'h100000,WAIT_WORD=22'h080000;
logic[21:0] state;
logic[CHUNK_COUNT_W-1:0] chunk_count;
logic[LANES-1:0] chunk_lane_allowed,word_lane_allowed,chunk_end_lane,chunk_data_allowed;
logic chunk_reaches_end;
logic[LANES:0] chunk_selected,step_word_boundary,step_saved_hit;
logic[p_word_shift+1:0] byte_offset_sum;
logic[31:0] next_byte_addr,stream_request_addr;
logic[16:0] group_remaining;
logic word_boundary,next_byte_saved_hit;
logic column_after_chunk,active_after_chunk,unused_stream_request_carry;
assign state=waiting?WAIT_WORD:STREAM;
'''
    selections = section(source, '  assign chunk_selected[0]', '  logic incoming_request,')
    address = section(source, '  if (CHUNK_COUNT_W + 1 < 32) begin : g_byte_address',
                      '  if (CHUNK_COUNT_W < 33) begin : g_reduction_position')
    words = section(source, '  assign byte_offset_sum=',
                    '  // 连续读取只在耗尽当前缓存字时发起')
    requests = section(source, '  // 连续读取只在耗尽当前缓存字时发起',
                       '  assign stream_context=')
    lanes = section(source, '  for (genvar lane = 0; lane < LANES; lane++) begin : g_word_lane',
                    '  // 偏移高字节的相邻值共用计算')
    chunks = section(source, "  always_comb begin\n    group_remaining={1'b0,c.group_c}",
                     '  // 字节移位仅选择当前自然地址分组内的有效数据')
    return declarations + selections + address + words + requests + lanes + chunks + '''
assign equivalent=
 chunk_reaches_end==(TILE_COUNT_W'(chunk_count)==col_remaining) &&
 next_byte_addr==(addr+(32'(chunk_count)<<c.input_s16)) &&
 word_boundary==(byte_offset_sum>=(p_word_shift+2)'(p_cache_read_bytes)) &&
 next_byte_saved_hit==(waiting ?
   next_byte_addr[31:p_word_shift]==addr[31:p_word_shift] :
   word_valid && word_addr=={next_byte_addr[31:p_word_shift],{p_word_shift{1'b0}}}) &&
 column_after_chunk==(TILE_COUNT_W'(chunk_count)<col_remaining) &&
 active_after_chunk==(TILE_COUNT_W'(chunk_count)<active_remaining) &&
 (!word_boundary || (stream_request_addr==next_byte_addr &&
   32'(chunk_count)==((32'(p_cache_read_bytes)-32'(addr[p_word_shift-1:0]))>>c.input_s16)));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = source_root / FRONTEND
    body = unit(path.read_text())
    test = out / 'stream_comparison.sv'
    test.write_text(body)
    profiles = [(size, lanes, bits, narrow)
                for size, lanes, bits in [(2, 1, 2), (4, 2, 2), (4, 4, 2),
                                         (16, 5, 3), (16, 7, 3), (16, 8, 3),
                                         (16, 16, 4), (4, 16, 4), (64, 8, 3)]
                for narrow in (1, 4, 8)]
    results = []
    for size, lanes, bits, narrow in profiles:
        name = f's{size}_l{lanes}_b{bits}_n{narrow}'
        script, log = out / (name + '.ys'), out / (name + '.log')
        sources = [source_root / 'rtl/npu/conv/conv_im2col_pkg.sv',
                   source_root / 'rtl/common/add_equal.sv',
                   source_root / 'rtl/common/parallel_prefix_add.sv', test]
        script.write_text('read_slang --top stream_comparison ' +
            f'-GSIZE={size} -GLANES={lanes} -Gp_word_shift={bits} -GNARROW_LANES={narrow} ' +
            ' '.join(shlex.quote(str(source)) for source in sources) +
            '\nprep -top stream_comparison -flatten\n' +
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        results.append({'case': name, 'passed': True, 'log': str(log)})
        print('FRONTEND_STREAM_EQUIVALENCE_PASS', name, flush=True)
    (out / 'summary.json').write_text(json.dumps({'passed': True, 'cases': results,
        'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()},
        'properties': ['完整32位下一地址、字边界与字命中结果',
                       '所有剩余元素计数及通道资格下的并行范围判断',
                       '末拍判断与完整通道编码后的定宽列比较一致',
                       '连续输出跨缓存字时，下一请求地址与原完整位宽地址相同',
                       '跨缓存字时，传输数量等于字内剩余的完整输入元素数']},
        ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
