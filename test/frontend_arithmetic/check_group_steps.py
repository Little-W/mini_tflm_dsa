#!/usr/bin/env python3
"""验证两种描述符通道组步长的完整结果与四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, bench, digest, run


def model(reference):
    match = re.search(r'  assign prepared_group_i_a = .*?'
                      r'  assign prepared_skip_group = skip_group_sum;', reference, re.S)
    if match is None:
        raise ValueError('描述符通道组计算语句未找到')
    body = match.group(0).replace('i_c.group_c', 'group_channels')
    return '''module match_proof(input logic [23:0] i_a,i_b,output logic equivalent);
logic [31:0] descriptor_reduction;
logic [15:0] group_channels;
logic [32:0] prepared_group_i_a,prepared_group_i_b,next_group_sum,skip_group_sum;
logic [32:0] prepared_next_group,prepared_skip_group,actual_next_group,actual_skip_group;
logic unused_next_group_carry,unused_skip_group_carry;
assign {descriptor_reduction,group_channels}={i_a,i_b};
conv_descriptor_group_steps u_actual(.i_reduction(descriptor_reduction),
 .i_group_channels(group_channels),.o_next_group(actual_next_group),.o_skip_group(actual_skip_group));
''' + body + '''
assign equivalent={actual_next_group,actual_skip_group}==={prepared_next_group,prepared_skip_group};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_descriptor_group_steps.sv')
    parser.add_argument('--reference', default='8cec74cc')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_descriptor.sv'],
                                        cwd=ROOT, text=True)
    generated = out/'group_steps.sv'
    generated.write_text(model(reference))
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([args.source.resolve(), generated], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    generated_bench = out/'tb.sv'
    generated_bench.write_text(bench(24))
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    formal, simulations = [], []
    for synthesis in (0, 1):
        name = f'synthesis{synthesis}'
        options = ['-DSYNTHESIS=1'] if synthesis else []
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options, *map(str, sources)])+
                         '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                         'prep -top match_proof -flatten\ncheck -assert\n'
                         'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('通道组步长形式证明未完成')
        formal.append(dict(synthesis=synthesis, passed=True, log_sha256=digest(log)))
        binary = out/(name+'.vvp')
        run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary,
             *simulation_sources, generated_bench], out/('compile_'+name+'.log'))
        log = out/('simulation_'+name+'.log')
        run(['vvp', binary], log)
        if 'WORD_MATCH_PASS width=24 checks=3170' not in log.read_text():
            raise ValueError('通道组步长四态检查未完成')
        simulations.append(dict(synthesis=synthesis, passed=True, checks=3170, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  reference=args.reference,
                  reference_source_sha256=hashlib.sha256(reference.encode()).hexdigest(),
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('GROUP_STEPS_PASS formal=2 four_state=6340')


if __name__ == '__main__':
    main()
