#!/usr/bin/env python3
"""验证按输出阶段预计算的推进范围与完整逐通道表达式。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import shlex
import sys

from check_word_match import ROOT, bench, digest, run


def model(lanes):
    width = (3*lanes+3)//2
    return f'''module match_proof(input logic [{width-1}:0] i_a,i_b,output logic equivalent);
logic first_allowed,word_output,actual,reference_value;
logic [{lanes-1}:0] static_lane,word_lane,after_lane,chunk_lane;
assign {{first_allowed,word_output,static_lane,word_lane,after_lane}}={{i_a,i_b}};
assign chunk_lane=static_lane & ({{{lanes}{{!word_output}}}}|word_lane);
assign reference_value=first_allowed && (&(~chunk_lane|after_lane));
conv_stream_range_after #(.p_lanes({lanes})) u_actual(
 .i_first_allowed(first_allowed),.i_word_output(word_output),.i_static_lane(static_lane),
 .i_word_lane(word_lane),.i_after_lane(after_lane),.o_after(actual));
assign equivalent=actual===reference_value;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_stream_range_after.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    source_hash = digest(source)
    formal, simulations = [], []
    for lanes in (1, 4, 8, 16, 33):
        generated = out/f'range_{lanes}.sv'
        generated.write_text(model(lanes))
        script, log = out/f'range_{lanes}.ys', out/f'formal_{lanes}.log'
        script.write_text(slang_command()+'--top match_proof '+shlex.join(map(str, [source, generated]))+
                         '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                         'prep -top match_proof -flatten\ncheck -assert\n'
                         'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('推进范围形式证明未完成')
        formal.append(dict(lanes=lanes, passed=True, log_sha256=digest(log)))
        width = (3*lanes+3)//2
        generated_bench = out/f'tb_{lanes}.sv'
        generated_bench.write_text(bench(width))
        binary = out/f'simulation_{lanes}.vvp'
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, source, generated, generated_bench],
            out/f'compile_{lanes}.log')
        log = out/f'simulation_{lanes}.log'
        run(['vvp', binary], log)
        checks = 2+32*(4*width+3)
        if f'WORD_MATCH_PASS width={width} checks={checks}' not in log.read_text():
            raise ValueError('推进范围四态检查未完成')
        simulations.append(dict(lanes=lanes, passed=True, checks=checks, log_sha256=digest(log)))
    if source_hash != digest(source):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256={str(source): source_hash},
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('RANGE_AFTER_PASS formal='+str(len(formal))+
          ' four_state='+str(sum(row['checks'] for row in simulations)))


if __name__ == '__main__':
    main()
