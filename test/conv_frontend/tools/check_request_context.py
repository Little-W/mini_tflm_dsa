#!/usr/bin/env python3
"""Verify request payload selection for every valid frontend request."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'test/frontend_pipeline'))
from source_sections import read_module


def incoming_context_unit(source, lanes, narrow):
    assign = lambda name: re.search(r'  assign ' + name + r'\s*=.*?;', source, re.S).group(0)
    row_unit = runpy.run_path(str(ROOT / 'test/frontend_group_feedback/check.py'))['row_unit']
    row = row_unit(source, lanes, narrow).replace('module comparison #(', 'module row_relation #(')
    context = re.search(r'    assign lane_context_allowed\[lane\] =.*?;', source, re.S).group(0)
    data = re.search(r'    assign chunk_data_allowed\[lane\] =.*?;', source, re.S).group(0)
    allowed = re.search(r'      chunk_lane_allowed\[lane\] =.*?;', source, re.S).group(0).strip()
    return row + f'''
module comparison #(parameter int LANES={lanes},NARROW_LANES={narrow})(
input logic[4:0] state_index,
input logic[LANES:0] group_range_q,active_lane_allowed_q,column_lane_allowed_q,
input logic[LANES-1:0] word_s8,word_s16,
input logic narrow_output,word_output_q,past_active_q,input_s16,row_last_q,
input logic wr_ready,cache_rsp_valid,cache_rsp_error,tile_valid,incoming_fast,incoming_accept,
input logic current_word_hit,word_boundary,row_base_valid,geometry_tile,next_row_padding,next_row_word_hit,
output logic equivalent);
import conv_im2col_frontend_pkg::*;
localparam bit REGISTER_DESCRIPTOR=0,REGISTER_ROW_ADDRESS=0;
st_t state;
logic chunk_reaches_end,wr_last,wr_valid,column_after_chunk,active_after_chunk,group_after_chunk;
logic[LANES-1:0] group_lane_allowed,lane_context_allowed,chunk_data_allowed,chunk_lane_allowed,word_lane_allowed;
logic incoming_context,reference_incoming_context,stream_request_eligible,row_request_eligible;
logic incoming_request,stream_next_request,next_row_request,cache_req_valid;
logic stream_context,request_row_context,reference_row_context;
assign state=st_t'(1)<<state_index;
assign group_lane_allowed=group_range_q[LANES-1:0];
assign word_lane_allowed=input_s16?word_s16:word_s8;
row_relation #(.LANES(LANES),.NARROW_LANES(NARROW_LANES)) u_row(
 .group_lane_allowed(group_lane_allowed),.word_s8(word_s8),.word_s16(word_s16),
 .active_lane_allowed_q(active_lane_allowed_q),.column_lane_allowed_q(column_lane_allowed_q),
 .narrow_output(narrow_output),.word_output_q(word_output_q),.past_active_q(past_active_q),.input_s16(input_s16),
 .actual_end(chunk_reaches_end),.expected_end(),.equivalent());
for(genvar lane=0;lane<LANES;lane++)begin:g_lane
{context}
{data}
assign {allowed}
end
assign column_after_chunk=column_lane_allowed_q[0]&&(&(~chunk_lane_allowed|column_lane_allowed_q[LANES:1]));
assign active_after_chunk=active_lane_allowed_q[0]&&(&(~chunk_lane_allowed|active_lane_allowed_q[LANES:1]));
assign group_after_chunk=group_range_q[0]&&(&(~chunk_lane_allowed|group_range_q[LANES:1]));
assign wr_last=row_last_q&&chunk_reaches_end;
assign wr_valid=state[$clog2(STREAM)]||state[$clog2(ZERO_STREAM)]||
    (state[$clog2(WAIT_WORD)]&&cache_rsp_valid&&!cache_rsp_error);
assign incoming_request=reference_incoming_context&&incoming_accept;
{assign('incoming_context')}
assign reference_incoming_context=incoming_context&&incoming_fast;
{assign('stream_request_eligible')}
{assign('row_request_eligible')}
{assign('stream_context')}
{assign('request_row_context')}
assign reference_row_context=(stream_context||state[$clog2(ZERO_STREAM)])&&row_request_eligible;
{assign('stream_next_request')}
{assign('next_row_request')}
{assign('cache_req_valid')}
assign equivalent=!(chunk_reaches_end&&column_after_chunk)&&
    (!cache_req_valid||((incoming_context==reference_incoming_context)&&
      (incoming_context||request_row_context==reference_row_context)));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path, source = read_module(root, 'stream')
    names = ('stream_context', 'stream_request_eligible', 'row_request_eligible',
             'request_stream_context', 'request_row_context', 'stream_next_request',
             'next_row_request', 'cache_req_valid', 'cache_req_addr')
    assignments = '\n'.join(re.search(
        r'  assign ' + name + r'\s*=.*?;', source, re.S).group(0) for name in names)
    rtl = out / 'request_context.sv'
    rtl.write_text('''module comparison(
input logic[4:0] state_index,
input logic wr_ready,cache_rsp_valid,cache_rsp_error,
input logic column_after_chunk,active_after_chunk,group_after_chunk,word_boundary,
input logic chunk_reaches_end,row_last_q,row_base_valid,geometry_tile,next_row_padding,next_row_word_hit,
input logic incoming_context,incoming_fetch,current_word_hit,
input logic[31:0] incoming_addr,next_row_addr,stream_request_addr,addr,
output logic equivalent
);
import conv_im2col_frontend_pkg::*;
localparam bit REGISTER_CACHE_REQUEST=1'b0,REGISTER_ROW_ADDRESS=1'b0;
st_t state;
logic wr_valid,incoming_request,stream_context,stream_request_eligible,row_request_eligible;
logic request_stream_context,request_row_context,stream_next_request,next_row_request,cache_req_valid;
logic[31:0] cache_req_addr,reference_addr;
logic[1:0] request_kind,reference_kind;
assign state=st_t'(1)<<state_index;
assign wr_valid=state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)] ||
    (state[$clog2(WAIT_WORD)] && cache_rsp_valid && !cache_rsp_error);
// 描述符请求成立时，接收状态已经选择对应的新描述符上下文。
assign incoming_request=incoming_context && incoming_fetch;
''' + assignments + '''
assign reference_addr=incoming_context?incoming_addr:next_row_request?next_row_addr:
    stream_context?stream_request_addr:addr;
assign reference_kind=incoming_context?2'd3:next_row_request?2'd2:stream_next_request?2'd1:2'd0;
assign request_kind=incoming_context?2'd3:request_row_context?2'd2:request_stream_context?2'd1:2'd0;
assign equivalent=(chunk_reaches_end && column_after_chunk) || !cache_req_valid ||
    (cache_req_addr==reference_addr && request_kind==reference_kind);
endmodule
''')
    packages = [root / 'rtl/npu/conv/conv_im2col_pkg.sv',
                root / 'rtl/npu/conv/conv_im2col_frontend_pkg.sv']
    script, log = out / 'request_context.ys', out / 'request_context.log'
    script.write_text('read_slang --top comparison ' + shlex.join(map(str, [*packages, rtl])) +
                      '\nprep -top comparison -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as handle:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                 '--worker', str(script)], stdout=handle,
                                stderr=subprocess.STDOUT, timeout=180)
    if result.returncode or 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    digest = lambda value: hashlib.sha256(value.read_bytes()).hexdigest()
    incoming_cases = []
    for lanes in (1,2,4,8,16):
        for narrow in sorted({min(lanes,4),min(lanes,8)}):
            name = f'incoming_lanes{lanes}_narrow{narrow}'
            incoming_rtl = out / (name + '.sv')
            incoming_script = out / (name + '.ys')
            incoming_log = out / (name + '.log')
            incoming_rtl.write_text(incoming_context_unit(source,lanes,narrow))
            incoming_script.write_text('read_slang --top comparison ' +
                shlex.join(map(str,[*packages,incoming_rtl])) +
                '\nprep -top comparison -flatten\ncheck -assert\n'
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            with incoming_log.open('w') as handle:
                result = subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                    '--worker',str(incoming_script)],stdout=handle,stderr=subprocess.STDOUT,timeout=180)
            if result.returncode or 'SAT proof finished - no model found: SUCCESS!' not in incoming_log.read_text():
                raise RuntimeError(str(incoming_log))
            incoming_cases.append({'lanes':lanes,'narrow_lanes':narrow,'passed':True,
                                   'log_sha256':digest(incoming_log)})
            print('INCOMING_CONTEXT_PASS',name,flush=True)
    report = {'passed': True, 'source_sha256': digest(path), 'formal_sha256': digest(rtl),
              'log_sha256': digest(log),
              'scope': 'Request address and coordinate context at every valid request',
              'incoming_context_cases': incoming_cases,
              'incoming_context_property': 'Every valid request uses the same incoming payload and metadata selection; '
                                           'prefetch captures only accepted valid requests',
              'state_relation': 'One-hot state; write valid follows STREAM, ZERO_STREAM, or a successful WAIT_WORD response',
              'row_relation': 'The actual lane-selection logic proves that chunk_reaches_end and column_after_chunk are mutually exclusive',
              'descriptor_relation': 'An incoming descriptor request selects its incoming context'}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('REQUEST_CONTEXT_PASS', flush=True)


if __name__ == '__main__':
    main()
