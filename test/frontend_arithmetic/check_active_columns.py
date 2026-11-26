#!/usr/bin/env python3
"""验证描述符有效列数的完整定宽计算及四态传播。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

from check_word_match import ROOT, bench, digest, run


def block(source):
    match = re.search(r'  if \(p_tile_count_w < 32\) begin : g_prepared_active_columns\n(.*?)'
                      r'  (?:assign prepared_group_i_a|conv_descriptor_group_steps)', source, re.S)
    if match is None:
        raise ValueError('描述符有效列数语句未找到')
    return '  if (p_tile_count_w < 32) begin : g_prepared_active_columns\n'+match.group(1)


def module(name, body):
    return f'''module {name} #(parameter int p_tile_count_w=5)(
 input logic [31:0] i_reduction_len, descriptor_reduction,
 input logic [p_tile_count_w-1:0] descriptor_columns,
 output logic [p_tile_count_w-1:0] prepared_active_columns);
{body}
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_descriptor.sv')
    parser.add_argument('--increment-source', type=Path, default=ROOT/'rtl/npu/conv/conv_channel_increment_match.sv')
    parser.add_argument('--reference', default='8b3728c008e6093095c8ade34aa4516145bc6005')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_descriptor.sv'],
                                        cwd=ROOT, text=True)
    helper = out/'column_helpers.sv'
    helper.write_text(module('actual_columns', block(source.read_text()))+
                      module('reference_columns', block(reference)))
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([args.increment_source.resolve(), helper], ROOT)
    hashes = {str(path): digest(path) for path in [source, *sources]}
    proofs, simulations = [], []
    for width in (1, 4, 5, 16, 31, 32, 40):
        stimulus_width = (64+width+1)//2
        model = out/f'column_{width}.sv'
        model.write_text(f'''module match_proof(input logic [{stimulus_width-1}:0] i_a,i_b,output logic equivalent);
logic [31:0] i_reduction_len,descriptor_reduction;
logic [{width-1}:0] descriptor_columns,actual,reference;
assign {{i_reduction_len,descriptor_reduction,descriptor_columns}}={{i_a,i_b}};
actual_columns #(.p_tile_count_w({width})) u_actual(.i_reduction_len,.descriptor_reduction,
 .descriptor_columns,.prepared_active_columns(actual));
reference_columns #(.p_tile_count_w({width})) u_reference(.i_reduction_len,.descriptor_reduction,
 .descriptor_columns,.prepared_active_columns(reference));
assign equivalent=actual===reference;
endmodule
''')
        for synthesis in (0, 1):
            name = f'width{width}_synthesis{synthesis}'
            script, log = out/(name+'.ys'), out/(name+'.log')
            options = ['-DSYNTHESIS=1'] if synthesis else []
            script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options, *map(str, sources), str(model)])+
                             '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                             'prep -top match_proof -flatten\ncheck -assert\n'
                             'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise ValueError('有效列数形式证明未完成')
            proofs.append(dict(width=width, synthesis=synthesis, passed=True, log_sha256=digest(log)))
        generated_bench = out/f'tb_{width}.sv'
        generated_bench.write_text(bench(stimulus_width))
        simulation_sources = []
        for path in sources:
            target = out/('simulation_'+path.name)
            target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer'))
            simulation_sources.append(target)
        binary = out/f'simulation_{width}.vvp'
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources, model,
             generated_bench], out/f'compile_{width}.log')
        log = out/f'simulation_{width}.log'
        run(['vvp', binary], log)
        expected = 2+32*(4*stimulus_width+3)
        if f'WORD_MATCH_PASS width={stimulus_width} checks={expected}' not in log.read_text():
            raise ValueError('有效列数四态检查未完成')
        simulations.append(dict(width=width, passed=True, checks=expected, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  reference=args.reference, reference_source_sha256=digest(helper),
                  formal=proofs, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('ACTIVE_COLUMNS_PASS formal='+str(len(proofs))+
          ' four_state='+str(sum(row['checks'] for row in simulations)))


if __name__ == '__main__':
    main()
