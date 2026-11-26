#!/usr/bin/env python3
"""从生产语句验证地址推进接收资格与描述符提交的完整逻辑关系。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

from check_word_match import ROOT, bench, digest, run


def assignment(source, name):
    result = re.search(r'  assign '+re.escape(name)+r'\s*=.*?;', source, re.S)
    if result is None:
        raise ValueError('输出接收语句未找到：'+name)
    return result.group(0)


def model(frontend, descriptor, stream):
    front = '\n'.join(assignment(frontend, name) for name in
        ('wr_valid', 'stream_output_accept', 'finishing_tile', 'descriptor_commit_eligible',
         'descriptor_state_context', 'stream_operation_accept', 'stream_transfer_accept', 'wr_last'))
    commit = assignment(descriptor, 'o_tile_commit')
    names = dict(o_tile_commit='tile_commit', o_tile_prepared_valid='tile_prepared_valid',
                 i_error='error', i_state='state', i_tile_finish='finishing_tile')
    for old, new in names.items():
        commit = re.sub(r'\b'+old+r'\b', new, commit)
    event = re.search(r'  always_comb begin\n    address_stream_write = .*?'
                      r'(?=  assign address_column_advance)', stream, re.S)
    if event is None:
        raise ValueError('流式接收资格语句未找到')
    return '''module match_proof(input logic [31:0] i_a,i_b,output logic equivalent);
import conv_im2col_frontend_pkg::*;
localparam bit REGISTER_DESCRIPTOR=1'b1;
localparam bit p_register_descriptor=1'b1;
logic [26:0] state;
logic tile_prepared_valid,error,cache_rsp_success,wr_ready,wr_last;
logic wr_valid,stream_output_accept,finishing_tile,descriptor_commit_eligible;
logic row_last_q,chunk_reaches_end,stream_transfer_accept,address_transfer_write;
logic descriptor_state_context,stream_operation_accept,tile_commit;
logic tile_valid,tile_admission_ready,tile_capture,address_stream_write;
assign {state,tile_prepared_valid,error,cache_rsp_success,wr_ready,row_last_q,chunk_reaches_end}={i_a,i_b[0]};
assign {tile_valid,tile_admission_ready,tile_capture}=3'b000;
wire i_wr_valid=wr_valid;
wire i_wr_ready=wr_ready;
wire i_tile_commit=tile_commit;
wire i_stream_operation_accept=stream_operation_accept;
wire i_stream_transfer_accept=stream_transfer_accept;
wire i_row_last_q=row_last_q;
wire o_chunk_reaches_end=chunk_reaches_end;
''' + front + '\n' + commit + '\n' + event.group(0) + '''
assign equivalent=
 ((address_transfer_write && chunk_reaches_end && !row_last_q)===
  (address_stream_write && chunk_reaches_end && !row_last_q)) &&
 ((address_transfer_write && !chunk_reaches_end)===
  (address_stream_write && !chunk_reaches_end));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_frontend.sv')
    parser.add_argument('--descriptor', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_descriptor.sv')
    parser.add_argument('--stream', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_stream.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    package = ROOT/'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    inputs = [args.frontend.resolve(), args.descriptor.resolve(), args.stream.resolve(), package]
    hashes = {str(path): digest(path) for path in inputs}
    generated = out/'transfer_accept.sv'
    generated.write_text(model(*(path.read_text() for path in inputs[:3])))
    script, formal_log = out/'transfer_accept.ys', out/'formal.log'
    script.write_text(slang_command()+'--top match_proof '+shlex.join(map(str,[package,generated]))+
                     '\nprep -top match_proof -flatten\ncheck -assert\n'
                     'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],formal_log)
    if 'SAT proof finished - no model found: SUCCESS!' not in formal_log.read_text():
        raise ValueError('输出接收资格形式证明未完成')
    generated_bench = out/'tb.sv'
    generated_bench.write_text(bench(32))
    binary = out/'simulation.vvp'
    run(['iverilog','-g2012','-s','tb','-o',binary,package,generated,generated_bench],out/'compile.log')
    simulation_log = out/'simulation.log'
    run(['vvp',binary],simulation_log)
    expected=4194
    if f'WORD_MATCH_PASS width=32 checks={expected}' not in simulation_log.read_text():
        raise ValueError('输出接收资格四态检查未完成')
    if any(digest(path)!=value for path,value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report=dict(passed=True,input_assumptions=[],source_sha256=hashes,
                formal=dict(passed=True,log_sha256=digest(formal_log)),
                four_state=dict(passed=True,checks=expected,log_sha256=digest(simulation_log)))
    (out/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('TRANSFER_ACCEPT_PASS formal=1 four_state='+str(expected))


if __name__=='__main__':
    main()
