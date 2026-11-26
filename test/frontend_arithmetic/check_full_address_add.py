#!/usr/bin/env python3
"""验证完整三十二位地址加法和含未知值的输出传播。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import ROOT, bench, digest, run
from formal_compilation import slang_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path,
                        default=ROOT/'rtl/npu/conv/conv_full_address_add.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    wrapper = out/'address_proof.sv'
    wrapper.write_text('''module match_proof(input logic [31:0] i_a,i_b,
output logic equivalent);
logic [31:0] actual;
conv_full_address_add u_actual(.i_a,.i_b,.o_sum(actual));
assign equivalent=actual===(i_a+i_b);
endmodule
''')
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve([args.source.resolve(), wrapper], ROOT)
    hashes = {str(path): digest(path) for path in sources}
    simulation_sources = []
    for path in sources:
        target = out/('simulation_'+path.name)
        target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer')
                          .replace('localparam int unsigned', 'localparam integer'))
        simulation_sources.append(target)
    tb = out/'tb.sv'
    tb.write_text(bench(32))
    formal, simulations = [], []
    for synthesis in (False, True):
        name = 'synthesis' if synthesis else 'generic'
        options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text(slang_command(options)+'--top match_proof '+
            shlex.join([*options, *map(str, sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top match_proof -flatten\ncheck -assert\n'
            'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
        if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
            raise ValueError('完整地址加法形式证明未完成')
        formal.append(dict(synthesis=synthesis, passed=True, log_sha256=digest(log)))
        binary = out/(name+'.vvp')
        run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary,
             *simulation_sources, tb], out/(name+'_compile.log'))
        log = out/(name+'_four_state.log')
        run(['vvp', binary], log)
        if 'WORD_MATCH_PASS width=32 checks=4194' not in log.read_text():
            raise ValueError('完整地址加法四态检查未完成')
        simulations.append(dict(synthesis=synthesis, passed=True, checks=4194,
                                log_sha256=digest(log)))
    if any(digest(path) != expected for path, expected in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, input_assumptions=[],
        source_sha256=hashes, formal=formal, four_state=simulations), indent=2)+'\n')
    print('FULL_ADDRESS_ADD_PASS formal=2 four_state=8388')


if __name__ == '__main__':
    main()
