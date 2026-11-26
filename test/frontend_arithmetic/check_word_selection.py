#!/usr/bin/env python3
"""验证生产字内范围选择的完整优先级及所有单通道四态输入组合。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from check_word_match import ROOT, digest, run


def model(source, reference):
    expected = re.search(r'      assign next_available\[byte_index\] = .*?;', reference, re.S)
    actual = re.search(r'        assign available_write_value\[byte_index\] = .*?running_available\[byte_index\];',
                       source, re.S)
    if expected is None or actual is None:
        raise ValueError('字内范围的生产选择语句未找到')
    expressions = expected.group(0)+'\n'+actual.group(0)
    for before, after in [('active_select_commit', 'i_commit'),
                          ('i_state[$clog2(ADDRESS_CHANNEL)]', 'i_channel'),
                          ('o_chunk_reaches_end', 'i_chunk_end'),
                          ('o_group_end_o_equal', 'i_group_end'),
                          ('i_coordinate_address_valid', 'i_coordinate_valid')]:
        expressions = expressions.replace(before, after)
    return '''module selection_proof #(parameter int p_bytes=8)(
input logic i_commit,i_channel,i_chunk_end,i_group_end,i_coordinate_valid,
input logic [p_bytes-1:0][4:0] source_available,output logic equivalent);
logic [p_bytes-1:0] next_available,available_write_value,running_available;
logic [p_bytes-1:0] row_available,tap_available,step_available;
for(genvar byte_index=0;byte_index<p_bytes;byte_index++)begin:g_byte
assign row_available[byte_index]=source_available[byte_index][1];
assign tap_available[byte_index]=source_available[byte_index][2];
assign step_available[byte_index]=source_available[byte_index][3];
'''+expressions+'''
end
conv_stream_word_select #(.p_bytes(p_bytes)) u_actual(
.i_chunk_end,.i_group_end,.i_coordinate_valid,.i_row(row_available),
.i_tap(tap_available),.i_step(step_available),.o_available(running_available));
assign equivalent=available_write_value===next_available;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_stream.sv')
    parser.add_argument('--helper', type=Path, default=ROOT/'rtl/npu/conv/conv_stream_word_select.sv')
    parser.add_argument('--reference', default='9bd6488c')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source, helper = args.source.resolve(), args.helper.resolve()
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_stream.sv'],
                                        cwd=ROOT, text=True)
    generated = out/'selection.sv'
    generated.write_text(model(source.read_text(), reference))
    sources = [helper, generated]
    hashes = {str(path): digest(path) for path in [source, *sources]}
    formal = []
    for width in (1, 4, 8, 16):
        for synthesis in (0, 1):
            options = ['-Gp_bytes='+str(width)]
            if synthesis:
                options += ['-DSYNTHESIS=1', '-DXILINX_FPGA=1']
            name = f'width{width}_synthesis{synthesis}'
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text(slang_command(options)+'--top selection_proof '+shlex.join([*options, *map(str, sources)])+
                              '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                              'prep -top selection_proof -flatten\ncheck -assert\n'
                              'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise ValueError('字内范围选择形式证明未完成')
            formal.append(dict(width=width, synthesis=synthesis, passed=True, log_sha256=digest(log)))
    tb = out/'tb.sv'
    tb.write_text('''module tb;
logic [9:0] value;
logic equivalent;
selection_proof #(.p_bytes(1)) u_proof(
.i_commit(value[9]),.i_channel(value[8]),.i_chunk_end(value[7]),
.i_group_end(value[6]),.i_coordinate_valid(value[5]),
.source_available(value[4:0]),.equivalent);
function automatic logic symbol(input integer code);
case(code) 0:symbol=1'b0;1:symbol=1'b1;2:symbol=1'bx;3:symbol=1'bz;endcase
endfunction
initial begin
for(integer sample=0;sample<1048576;sample=sample+1)begin
for(integer bit_index=0;bit_index<10;bit_index=bit_index+1)
value[bit_index]=symbol((sample>>(2*bit_index))&3);
#1;
if(equivalent!==1'b1)$fatal(1,"选择结果不一致 sample=%0d value=%b",sample,value);
end
$display("WORD_SELECTION_PASS checks=1048576");
$finish;
end
endmodule
''')
    simulations = []
    for synthesis in (0, 1):
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        binary = out/f'synthesis{synthesis}.vvp'
        run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary, *sources, tb],
            out/f'compile{synthesis}.log')
        log = out/f'simulation{synthesis}.log'
        run(['vvp', binary], log)
        if 'WORD_SELECTION_PASS checks=1048576' not in log.read_text():
            raise ValueError('完整四态输入组合检查未完成')
        simulations.append(dict(synthesis=synthesis, passed=True, checks=1048576, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, reference=args.reference, input_assumptions=[],
                  source_sha256=hashes, formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('WORD_SELECTION_PASS formal=8 four_state=2097152')


if __name__ == '__main__':
    main()
