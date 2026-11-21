#!/usr/bin/env python3
"""证明前端通道范围、预读分段及参数化分组加法的完整位宽等价性。"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = 'rtl/npu/conv/conv_im2col_frontend.sv'
PACKAGE = 'rtl/npu/conv/conv_im2col_pkg.sv'
HELPERS = ('rtl/common/add_equal.sv', 'rtl/common/parallel_prefix_add.sv')


def group_unit(source):
    start = re.search(r'  if \(LANES <= \d+\) begin : g_short_group_lane', source).start()
    end = source.index('  end else if (LANES <= 32768) begin : g_group_lane_range', start)
    body = source[start:end] + '\n  end\n'
    result = '''module group_comparison #(parameter int LANES=4, CHUNK_COUNT_W=$clog2(LANES+1)) (
input conv_im2col_pkg::conv_cfg_t c,cfg,
input logic [15:0] ch_q,
input logic [5:0][15:0] group_range_channel,
input logic [LANES-1:0] chunk_lane_allowed,
output logic equivalent);
logic [4:0] group_range_q,group_range_cfg;
logic [5:0][4:0] group_range_next;
logic [LANES-1:0] group_lane_allowed;
logic [15:0] last_group_channel_q,group_minus_two_q,group_minus_three_q,group_minus_four_q;
logic [CHUNK_COUNT_W-1:0] chunk_count;
logic group_after_chunk;
logic [16:0] group_remaining;
logic [4:0] expected_cfg;
logic [5:0][4:0] expected_next;
logic [5:0][15:0] expected_channel;
logic [4:1] group_at_least_q;
for(genvar threshold=1;threshold<=4;threshold++)
 assign group_at_least_q[threshold]=c.group_c>=16'(threshold);
assign last_group_channel_q=c.group_c-16'd1;
assign group_minus_two_q=c.group_c-16'd2;
assign group_minus_three_q=c.group_c-16'd3;
assign group_minus_four_q=c.group_c-16'd4;
assign group_remaining={1'b0,c.group_c}-{1'b0,ch_q};
always_comb begin
 chunk_count='0;
 for(int lane=0;lane<LANES;lane++)
  if(chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
end
for(genvar source=0;source<6;source++) begin
 assign expected_channel[source]=source==5 ? ch_q+16'(chunk_count) : group_range_channel[source];
 for(genvar lane=0;lane<5;lane++) begin
  assign expected_next[source][lane]=17'(lane)<({1'b0,c.group_c}-{1'b0,expected_channel[source]});
 end
end
for(genvar lane=0;lane<5;lane++) begin
 assign group_range_q[lane]=17'(lane)<group_remaining;
 assign expected_cfg[lane]=17'(lane)<({1'b0,cfg.group_c}-{1'b0,ch_q});
end
''' + body + '''
assign equivalent=group_range_cfg==expected_cfg && group_range_next==expected_next &&
 group_after_chunk==(17'(chunk_count)<group_remaining) && group_lane_allowed==group_range_q[LANES-1:0];
endmodule
'''
    if 'p_saved_group_lanes' in source:
        result = result.replace('output logic equivalent);',
            'output logic equivalent);\nlocalparam int p_saved_group_lanes=LANES>4 ? 8 : 4;')
        result = result.replace('[4:0]', '[p_saved_group_lanes:0]').replace('[4:1]', '[p_saved_group_lanes:1]')
        result = result.replace('threshold<=4', 'threshold<=p_saved_group_lanes')
        result = result.replace('lane<5', 'lane<=p_saved_group_lanes')
        marker = 'assign last_group_channel_q='
        where = result.index(marker)
        result = result[:where] + '''logic [p_saved_group_lanes-1:0][15:0] group_last_channels_q;
for(genvar boundary=0;boundary<p_saved_group_lanes;boundary++)
 assign group_last_channels_q[boundary]=c.group_c-16'(boundary+1);
''' + result[where:]
    return result


def prefetch_unit(source):
    start = source.index('  // 预读上下文在第一阶段准备纵向增量')
    end = source.index('  // 较大通道数按缓存行预测后续像素', start)
    return '''module prefetch_comparison(
input conv_im2col_pkg::conv_cfg_t c,
input logic signed [34:0] pfa_y,
input logic [15:0] pfa_kernel_y,
input logic [31:0] pfa_kernel_x,pf_distance_q,
output logic equivalent);
logic signed [16:0] pf_y_delta,pf_y_delta_q;
logic signed [17:0] pf_y_wrap_delta,pf_y_wrap_delta_q;
logic [15:0] pf_y_step;
logic [2:0][31:0] pf_prepare_i_a,pf_prepare_i_b,pf_prepare_o_sum;
logic pf_prepare_i_carry;
logic [2:0] unused_pf_prepare_carry;
logic pf_stream_lookahead;
logic [31:0] expected_y,expected_wrapped,expected_kernel;
assign pf_stream_lookahead=c.windowed && c.input_c>=16'd16;
assign pf_y_delta_q=pf_y_delta;
assign pf_y_wrap_delta_q=pf_y_wrap_delta;
''' + source[start:end] + '''
always_comb begin
 expected_y=32'(pfa_y);
 if(pf_stream_lookahead && c.stride_h==16'd1 && c.dilation_h==16'd1)
  expected_y=expected_y+32'(c.kernel_h)-32'd1-32'(pfa_kernel_y);
 expected_wrapped=expected_y+(pf_stream_lookahead ? 32'(c.stride_h) :
  (c.kernel_h==16'd1 ? 32'(c.stride_h) : 32'(c.dilation_h)));
 expected_kernel=pfa_kernel_x+pf_distance_q;
end
assign equivalent=pf_prepare_o_sum=={expected_kernel,expected_wrapped,expected_y};
endmodule
'''


def configuration_unit(source):
    start = source.index('  logic [LINE_BYTES:0] cfg_line_threshold')
    end = source.index('  always_ff @(posedge clk or negedge rst_n)', start)
    return '''module configuration_comparison #(parameter int LINE_BYTES=16)(
input conv_im2col_pkg::conv_cfg_t cfg,output logic equivalent);
logic [31:0] cfg_pixel_bytes,cfg_line_pixels,cfg_pf_step;
logic [31:0] expected_pixels,expected_step;
''' + source[start:end] + '''
always_comb begin
 expected_pixels=32'd1;
 for(int count=1;count<=LINE_BYTES;count++)
  if(cfg_pixel_bytes<=32'((LINE_BYTES-1)/count)) expected_pixels=32'(count)+32'd1;
 expected_step=cfg.kernel_w==16'd1 ? 32'(cfg.stride_w) : 32'(cfg.dilation_w);
 if(expected_step<expected_pixels) expected_step=expected_pixels;
end
assign equivalent=cfg_line_pixels==expected_pixels && cfg_pf_step==expected_step;
endmodule
'''


def adder_unit(width, group, preserve):
    return f'''module adder_comparison(input logic [{width-1}:0] a,b,input logic carry,
output logic equivalent);
logic [{width-1}:0] result;logic result_carry;
parallel_prefix_add #(.p_width({width}),.p_group_width({group}),.p_preserve_groups(1'b{preserve})) u_sum(
.i_a(a),.i_b(b),.i_carry(carry),.o_sum(result),.o_carry(result_carry));
assign equivalent={{result_carry,result}}==({{1'b0,a}}+{{1'b0,b}}+{width+1}'(carry));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (source_root / FRONTEND).read_text()
    cases = []
    for lanes in ((1, 2, 4, 5, 7, 8) if 'p_saved_group_lanes' in source else (1, 2, 4)):
        cases.append((f'group_l{lanes}', 'group_comparison', group_unit(source), [f'-GLANES={lanes}']))
    cases.append(('prefetch', 'prefetch_comparison', prefetch_unit(source), []))
    for line_bytes in (8, 16, 64, 128):
        cases.append((f'configuration_line{line_bytes}', 'configuration_comparison',
                      configuration_unit(source), [f'-GLINE_BYTES={line_bytes}']))
    for width in (1, 7, 9, 17, 18, 32, 35):
        for group in (4, 8):
            for preserve in (0, 1):
                cases.append((f'add_w{width}_g{group}_k{preserve}', 'adder_comparison',
                              adder_unit(width, group, preserve), []))
    results = []
    for label, top, rtl, options in cases:
        target = out / (label + '.sv')
        target.write_text(rtl)
        script = out / (label + '.ys')
        log = out / (label + '.log')
        files = [source_root / PACKAGE, *(source_root / name for name in HELPERS), target]
        script.write_text('read_slang --top ' + top + ' ' + ' '.join(options) + ' ' +
            ' '.join(shlex.quote(str(path)) for path in files) + '\nprep -top ' + top +
            ' -flatten\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], cwd=ROOT, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise RuntimeError('组合证明未完成: ' + label)
        results.append({'case': label, 'passed': True,
                        'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
        print('FRONTEND_ARITHMETIC_PROOF_PASS', label, flush=True)
    paths = (FRONTEND, PACKAGE, *HELPERS)
    report = {'passed': True, 'inputs_constrained': False, 'cases': results,
              'source_sha256': {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                                for name in paths}}
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
