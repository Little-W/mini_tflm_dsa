#!/usr/bin/env python3
"""验证传输步长选择后的完整通道索引及四态传播。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import runpy
import shlex
import sys

from check_word_match import ROOT, bench, digest, run
from formal_compilation import slang_command


def reference_statement(lanes):
    return f'''logic [{lanes}:0][17:0] reference_step;
for(genvar step=0;step<={lanes};step++)begin:g_reference
 logic [17:0] sum_bits,carry_bits;
 assign sum_bits={{2'b0,offset}}^channel^18'(step);
 assign carry_bits=(({{2'b0,offset}}&channel)|
   (({{2'b0,offset}}|channel)&18'(step)))<<1;
 assign reference_step[step]=sum_bits+carry_bits;
end
always_comb begin
 expected='0;
 for(int step=0;step<={lanes};step++)expected|={{18{{selected[step]}}}}&reference_step[step];
end
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path,
                        default=ROOT/'rtl/npu/conv/conv_stream_epoch_sum.sv')
    parser.add_argument('--helpers', type=Path, nargs='*', default=[])
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    formal, simulations, hashes = [], [], {}
    for lanes in (1, 2, 3, 4, 7, 8, 16):
        wrapper = out/f'epoch{lanes}.sv'
        wrapper.write_text(f'''module match_proof(input logic [31:0] i_a,i_b,
output logic equivalent);
logic [15:0] offset;
logic [17:0] channel,actual,expected;
logic [{lanes}:0] selected;
assign {{selected,channel,offset}}={{i_a,i_b}};
conv_stream_epoch_sum #(.p_lanes({lanes})) u_actual(
 .i_offset(offset),.i_channel(channel),.i_selected(selected),.o_sum(actual));
'''+reference_statement(lanes)+'''assign equivalent=actual===expected;
endmodule
''')
        sources = resolve([args.source.resolve(), wrapper,
                           *[path.resolve() for path in args.helpers]], ROOT)
        hashes.update({str(path): digest(path) for path in sources})
        simulation_sources = []
        for path in sources:
            target = out/('simulation_'+path.name)
            target.write_text(path.read_text().replace('parameter int unsigned', 'parameter integer')
                              .replace('localparam int unsigned', 'localparam integer'))
            simulation_sources.append(target)
        tb = out/f'tb{lanes}.sv'
        tb.write_text(bench(32).replace('trial<32', 'trial<128'))
        for synthesis in (False, True):
            name = f'lanes{lanes}_'+('synthesis' if synthesis else 'generic')
            options = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
            script, log = out/(name+'.ys'), out/(name+'.log')
            script.write_text(slang_command(options)+'--top match_proof '+
                shlex.join([*options, *map(str, sources)])+
                '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                'prep -top match_proof -flatten\ncheck -assert\n'
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise ValueError('完整通道索引形式证明未完成')
            formal.append(dict(lanes=lanes, synthesis=synthesis, passed=True, log_sha256=digest(log)))
            binary = out/(name+'.vvp')
            run(['iverilog', '-g2012', *options, '-s', 'tb', '-o', binary,
                 *simulation_sources, tb], out/(name+'_compile.log'))
            log = out/(name+'_four_state.log')
            run(['vvp', binary], log)
            checks = 2+128*(4*32+3)
            if f'WORD_MATCH_PASS width=32 checks={checks}' not in log.read_text():
                raise ValueError('完整通道索引四态检查未完成')
            simulations.append(dict(lanes=lanes, synthesis=synthesis, passed=True,
                                    checks=checks, log_sha256=digest(log)))
            print(name+' PASS', flush=True)
    if any(digest(path) != expected for path, expected in hashes.items()):
        raise ValueError('验证期间源文件发生变化')
    report = dict(passed=True, input_assumptions=[], selection_encoding_assumptions=[],
                  source_sha256=hashes, formal=formal, four_state=simulations)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'EPOCH_SUM_PASS formal={len(formal)} four_state={sum(x["checks"] for x in simulations)}')


if __name__ == '__main__':
    main()
