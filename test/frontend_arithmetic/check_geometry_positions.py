#!/usr/bin/env python3
"""检查生产位置译码的零值和列末比较，覆盖全部二态输入及逐位四态样本。"""
from __future__ import annotations

from formal_compilation import slang_command

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

from check_word_match import ROOT, bench, digest, run


def model(source):
    zero = re.search(r'  \(\* keep = "true" \*\) logic \[5:0\] position_nonzero_group;.*?'
                     r'assign position_nonzero = \|position_nonzero_group;', source, re.S)
    wrap = re.search(r'  \(\* keep = "true" \*\) logic \[5:0\] power_wrap_group;.*?'
                     r'assign fast_wrap_value\[2\] = .*?;', source, re.S)
    if zero is None or wrap is None:
        raise ValueError('位置分组比较语句未找到')
    block = zero.group(0) + '\n' + wrap.group(0)
    block = block.replace('i_c.output_w', 'output_width')
    return '''module match_proof(input logic [39:0] i_a, i_b, output logic equivalent);
logic [31:0] p_decode;
logic [15:0] o_last_output_col_q, p_cache_x, output_width;
logic [3:0] fast_wrap_value;
assign {p_decode, o_last_output_col_q, p_cache_x, output_width}={i_a,i_b};
''' + block + '''
assign equivalent=(position_nonzero===(p_decode!=32'd0)) &&
 (fast_wrap_value[1]===((p_decode[15:0]&o_last_output_col_q)==o_last_output_col_q)) &&
 (fast_wrap_value[2]===((output_width!=16'd0)&&(p_cache_x==o_last_output_col_q)));
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=ROOT/'rtl/npu/conv/conv_im2col_geometry.sv')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    helper = ROOT/'rtl/npu/conv/conv_descriptor_match.sv'
    hashes = {str(path): digest(path) for path in (source, helper)}
    generated = out/'position_comparisons.sv'
    generated.write_text(model(source.read_text()))
    script, formal_log = out/'position_comparisons.ys', out/'formal.log'
    script.write_text(slang_command()+'--top match_proof '+shlex.join(map(str, [helper, generated]))+
                     '\nprep -top match_proof -flatten\ncheck -assert\n'
                     'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    run([sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker', script], formal_log)
    if 'SAT proof finished - no model found: SUCCESS!' not in formal_log.read_text():
        raise ValueError('位置比较形式证明未完成')
    simulation_helper = out/helper.name
    simulation_helper.write_text(helper.read_text().replace('parameter int unsigned', 'parameter integer'))
    generated_bench = out/'tb.sv'
    generated_bench.write_text(bench(40))
    binary = out/'simulation.vvp'
    run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, simulation_helper,
         generated, generated_bench], out/'compile.log')
    simulation_log = out/'simulation.log'
    run(['vvp', binary], simulation_log)
    expected = 2+32*(4*40+3)
    if f'WORD_MATCH_PASS width=40 checks={expected}' not in simulation_log.read_text():
        raise ValueError('位置比较四态检查未完成')
    if any(digest(path) != value for path, value in hashes.items()):
        raise ValueError('验证期间生产源码发生变化')
    report = dict(passed=True, input_assumptions=[], source_sha256=hashes,
                  formal=dict(passed=True, log_sha256=digest(formal_log)),
                  four_state=dict(passed=True, checks=expected, log_sha256=digest(simulation_log)))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('GEOMETRY_POSITION_PASS formal=1 four_state='+str(expected))


if __name__ == '__main__':
    main()
