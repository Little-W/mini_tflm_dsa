#!/usr/bin/env python3
"""验证两种输入格式的提前范围归并及完整四态选择语义。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys

from check_word_match import ROOT, bench, digest, run
from formal_compilation import slang_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path,
                        default=ROOT/'rtl/npu/conv/conv_stream_format_range.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    hashes = {str(source): digest(source)}
    formal, simulations = [], []
    for lanes in (1, 4, 8, 16, 33):
        width = (4*lanes+4)//2
        wrapper = out/f'range{lanes}.sv'
        wrapper.write_text(f'''module match_proof(input logic [{width-1}:0] i_a,i_b,
output logic equivalent);
logic first_allowed,word_output,input_s16,actual,expected;
logic [{lanes-1}:0] static_lane,word_s8,word_s16,after_lane,word_lane,chunk_lane;
assign {{first_allowed,word_output,input_s16,static_lane,word_s8,word_s16,after_lane}}={{i_a,i_b}};
assign word_lane=input_s16?word_s16:word_s8;
assign chunk_lane=static_lane&({{{lanes}{{!word_output}}}}|word_lane);
assign expected=first_allowed&&(&(~chunk_lane|after_lane));
conv_stream_format_range #(.p_lanes({lanes})) u_actual(
 .i_first_allowed(first_allowed),.i_static_lane(static_lane),.i_word_s8(word_s8),
 .i_word_s16(word_s16),.i_after_lane(after_lane),.i_word_output(word_output),
 .i_input_s16(input_s16),.o_after(actual));
assign equivalent=actual===expected;
endmodule
''')
        hashes[str(wrapper)] = digest(wrapper)
        script, log = out/f'range{lanes}.ys', out/f'formal{lanes}.log'
        script.write_text(slang_command()+'--top match_proof '+
            shlex.join(map(str, [source, wrapper]))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top match_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('输入格式范围形式证明未完成')
        formal.append(dict(lanes=lanes, passed=True, log_sha256=digest(log)))
        tb = out/f'tb{lanes}.sv'
        tb.write_text(bench(width))
        binary = out/f'range{lanes}.vvp'
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, source, wrapper, tb],
            out/f'compile{lanes}.log')
        log = out/f'simulation{lanes}.log'
        run(['vvp', binary], log)
        checks = 2+32*(4*width+3)
        if f'WORD_MATCH_PASS width={width} checks={checks}' not in log.read_text():
            raise ValueError('输入格式范围四态比较未完成')
        simulations.append(dict(lanes=lanes, passed=True, checks=checks,
                                log_sha256=digest(log)))
    if any(digest(path) != expected for path, expected in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'FORMAT_RANGE_PASS formal={len(formal)} four_state={sum(x["checks"] for x in simulations)}')


if __name__ == '__main__':
    main()
