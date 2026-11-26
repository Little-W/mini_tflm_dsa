#!/usr/bin/env python3
"""验证核列短步长与完整十六位模加比较。"""
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
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_kernel_step_equal.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    generated = out/'kernel_step.sv'
    generated.write_text('''module match_proof(input logic [17:0] i_a,i_b,output logic equivalent);
logic [15:0] base,last,reference_sum;
logic signed [2:0] step;
logic actual;
assign {base,step,last}={i_a,i_b};
assign reference_sum=base+16'($signed(step));
conv_kernel_step_equal u_actual(.i_base(base),.i_step(step),.i_last(last),.o_equal(actual));
assign equivalent=actual===(reference_sum==last);
endmodule
''')
    dependencies = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = dependencies([args.source.resolve(), generated], ROOT)
    hashes = {str(p): digest(p) for p in sources}
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer').replace(
            'localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    tb = out/'tb.sv'
    tb.write_text(bench(18).replace('trial<32', 'trial<128'))
    formal, simulations = [], []
    for synthesis in (0, 1):
        name = 'synthesis'+str(synthesis)
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(slang_command(options)+'--top match_proof '+shlex.join([*options, *map(str, sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top match_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('核列短步长形式证明未完成')
        formal.append(dict(synthesis=synthesis, passed=True, log_sha256=digest(log)))
        binary = out/(name+'.vvp')
        run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary, *simulation_sources, tb],
            out/('compile_'+name+'.log'))
        log = out/('simulation_'+name+'.log')
        run(['vvp', binary], log)
        if 'WORD_MATCH_PASS width=18 checks=9602' not in log.read_text():
            raise ValueError('核列短步长四态比较未完成')
        simulations.append(dict(synthesis=synthesis, passed=True, checks=9602, log_sha256=digest(log)))
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, input_assumptions=[],
        source_sha256=hashes, formal=formal, four_state=simulations), ensure_ascii=False, indent=2)+'\n')
    print('KERNEL_STEP_PASS formal=2 four_state=19204')


if __name__ == '__main__':
    main()
