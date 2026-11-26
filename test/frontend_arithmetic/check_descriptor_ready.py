#!/usr/bin/env python3
"""从实际控制语句证明描述符接收资格及未知输入传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

from check_transfer_accept import assignment
from check_word_match import ROOT, bench, digest, run


def model(frontend, descriptor, registered):
    statements = '\n'.join(assignment(frontend, name) for name in
        ('wr_valid', 'stream_output_accept', 'finishing_tile', 'wr_last',
         'tile_ready_static', 'tile_ready_context'))
    context = re.search(r'  conv_im2col_tile_context u_tile_context \(.*?\n  \);', frontend, re.S)
    ready = re.search(r'  always_comb begin\n    tile_ready =.*?(?=  assign busy)', frontend, re.S)
    if context is None or ready is None:
        raise ValueError('描述符接收的生产语句未找到')
    commit = assignment(descriptor, 'o_tile_commit')
    for old, new in dict(o_tile_commit='tile_commit', o_tile_prepared_valid='tile_prepared_valid',
                         i_error='error', i_state='state', i_tile_finish='finishing_tile',
                         p_register_descriptor='REGISTER_DESCRIPTOR').items():
        commit = re.sub(r'\b'+old+r'\b', new, commit)
    return f'''module match_proof(input logic [31:0] i_a,i_b,output logic equivalent);
import conv_im2col_frontend_pkg::*;
localparam bit REGISTER_DESCRIPTOR=1'b{registered};
logic [26:0] state;
logic [2:0] cfg_prepare_phase;
logic [1:0] address_step_phase;
logic configured,error,pred_busy,pred_cfg_busy,pred_cfg_pending,cache_cfg_pending,cache_hint_pending;
logic tile_prepared_valid,cfg_valid,wr_ready,row_last_q,chunk_reaches_end,cache_rsp_success,tile_capture;
logic wr_valid,wr_last,stream_output_accept,finishing_tile,tile_commit;
logic tile_ready_static,tile_ready_context,tile_ready,reference_ready;
logic [1:0] tile_context_ready;
assign {{state,cfg_prepare_phase,address_step_phase,configured,error,pred_busy,pred_cfg_busy,
  pred_cfg_pending,cache_cfg_pending,cache_hint_pending,tile_prepared_valid,cfg_valid,wr_ready,
  row_last_q,chunk_reaches_end,cache_rsp_success,tile_capture}}={{i_a,i_b}};
''' + statements + '\n' + context.group(0) + '\n' + commit + '\n' + ready.group(0) + '''
assign reference_ready=tile_ready_context && !cfg_valid &&
  (!REGISTER_DESCRIPTOR || !tile_prepared_valid || tile_commit);
assign equivalent=tile_ready===reference_ready;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_frontend.sv')
    parser.add_argument('--descriptor', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_descriptor.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    package = ROOT/'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    context = ROOT/'rtl/npu/conv/conv_im2col_tile_context.sv'
    inputs = [args.frontend.resolve(), args.descriptor.resolve(), package, context]
    hashes = {str(path): digest(path) for path in inputs}
    tb = out/'tb.sv'
    tb.write_text(bench(32))
    formal, simulations = [], []
    for registered in (0, 1):
        wrapper = out/f'ready{registered}.sv'
        wrapper.write_text(model(inputs[0].read_text(), inputs[1].read_text(), registered))
        for synthesis in (0, 1):
            name = f'registered{registered}_synthesis{synthesis}'
            options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            sources = [package, context, wrapper]
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options, *map(str, sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top match_proof -flatten\ncheck -assert\n'
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise ValueError('描述符接收形式证明未完成')
            formal.append(dict(name=name, passed=True, log_sha256=digest(log)))
            binary = out/(name+'.vvp')
            run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary, *sources, tb],
                out/('compile_'+name+'.log'))
            log = out/('simulation_'+name+'.log')
            run(['vvp', binary], log)
            if 'WORD_MATCH_PASS width=32 checks=4194' not in log.read_text():
                raise ValueError('描述符接收四态比较未完成')
            simulations.append(dict(name=name, passed=True, checks=4194, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], state_encoding_assumptions=[], source_sha256=hashes,
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('DESCRIPTOR_READY_PASS formal=4 four_state=16776')


if __name__ == '__main__':
    main()
