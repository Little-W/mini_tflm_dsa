#!/usr/bin/env python3
"""验证固定字标签步长比较与完整加法匹配的组合结果。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import bench, digest, run

ROOT = Path(__file__).resolve().parents[2]


def model(width):
    return f'''module match_proof(
input logic [{width-1}:0] i_a,i_b,output logic equivalent);
logic [3:0] actual_match,reference_match;
for(genvar step=0;step<4;step++)begin:g_step
 conv_word_step_match #(.p_width({width}),.p_step(step)) u_actual(
  .i_a,.i_target(i_b),.o_equal(actual_match[step]));
 add_equal #(.p_width({width})) u_reference(
  .i_a,.i_b({width}'(step)),.i_target(i_b),.i_carry_in(1'b0),.o_equal(reference_match[step]));
end
assign equivalent=actual_match===reference_match;
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, nargs='*', default=[])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    overrides = {path.name: path.resolve() for path in args.candidate}
    names = ('conv_word_step_match.sv', 'conv_channel_increment_match.sv', 'conv_descriptor_match.sv')
    sources = [overrides.get(name, ROOT/'rtl/npu/conv'/name) for name in names]
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies(sources, ROOT)
    hashes = {str(path): digest(path) for path in sources}
    formal, simulations = [], []
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    for width in (1, 2, 5, 16, 29, 32, 35):
        generated = out/f'word_steps_{width}.sv'
        generated.write_text(model(width))
        script, log = out/f'word_steps_{width}.ys', out/f'formal_{width}.log'
        script.write_text(slang_command()+'--top match_proof '+shlex.join(
            [*map(str, sources), str(generated)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top match_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('字标签步长形式证明未完成')
        formal.append(dict(width=width, steps=[0, 1, 2, 3], passed=True, log_sha256=digest(log)))
        generated_bench = out/f'tb_{width}.sv'
        generated_bench.write_text(bench(width))
        binary = out/f'simulation_{width}.vvp'
        run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, *simulation_sources,
             generated, generated_bench], out/f'compile_{width}.log')
        log = out/f'simulation_{width}.log'
        run(['vvp', binary], log)
        checks = 2+32*(4*width+3)
        if f'WORD_MATCH_PASS width={width} checks={checks}' not in log.read_text():
            raise ValueError('字标签步长四态检查未完成')
        simulations.append(dict(width=width, steps=[0, 1, 2, 3], checks=checks,
                                passed=True, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('WORD_STEPS_PASS formal='+str(len(formal))+
          ' four_state='+str(sum(item['checks'] for item in simulations)))


if __name__ == '__main__':
    main()
