#!/usr/bin/env python3
"""验证配置、描述符和运行阶段的通道范围选择及四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import ROOT, bench, digest, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([args.source.resolve()], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    formal, simulations = [], []
    for width in (1, 5, 9, 17):
        input_width = (8*width+8)//2
        model = out/f'value_{width}.sv'
        model.write_text(f'''module match_proof(
input logic [{input_width-1}:0] i_a,i_b,output logic equivalent);
logic configure,commit,chunk_end;
logic [3:0] decoded;
logic [7:0][{width-1}:0] candidate;
logic [7:0] selected;
logic [{width-1}:0] expected,actual;
assign {{configure,commit,decoded,chunk_end,candidate}}={{i_a,i_b}};
conv_group_range_choice u_choice(.i_configure(configure),.i_commit(commit),
 .i_decoded_source(decoded),.i_chunk_end(chunk_end),.o_select(selected));
conv_group_range_select #(.p_choices(8),.p_width({width})) u_reference(
 .i_select(selected),.i_data(candidate),.o_data(expected));
conv_stream_group_value #(.p_width({width})) u_actual(
 .i_configure(configure),.i_commit(commit),.i_decoded_source(decoded),
 .i_chunk_end(chunk_end),.i_candidate(candidate),.o_value(actual));
assign equivalent=actual===expected;
endmodule
''')
        tb = out/f'tb_{width}.sv'
        tb.write_text(bench(input_width))
        for synthesis in (False, True):
            name = f'width{width}_'+('synthesis' if synthesis else 'generic')
            options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text(slang_command(options)+'--top match_proof '+shlex.join(
                [*options, *map(str, sources), str(model)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'+
                'prep -top match_proof -flatten\ncheck -assert\n'+
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SUCCESS!' not in log.read_text():
                raise ValueError('完整范围选择形式证明未完成')
            formal.append(dict(width=width, synthesis=synthesis, passed=True,
                               log_sha256=digest(log)))
            binary = out/(name+'.vvp')
            run(['iverilog', '-g2012', '-s', 'tb', *options, '-o', binary,
                 *sources, model, tb], out/(name+'_compile.log'))
            sim = out/(name+'_simulation.log')
            run(['vvp', binary], sim)
            checks = 2+32*(4*input_width+3)
            if f'WORD_MATCH_PASS width={input_width} checks={checks}' not in sim.read_text():
                raise ValueError('完整范围选择四态比较未完成')
            simulations.append(dict(width=width, synthesis=synthesis, checks=checks,
                                    passed=True, log_sha256=digest(sim)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    report = dict(passed=True, input_constraints=[], source_sha256=hashes,
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('GROUP_VALUE_PASS formal='+str(len(formal))+
          ' four_state='+str(sum(row['checks'] for row in simulations)))


if __name__ == '__main__':
    main()
