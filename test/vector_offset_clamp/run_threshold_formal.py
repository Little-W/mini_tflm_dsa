#!/usr/bin/env python3
"""验证配置阈值提前计算后的完整六十四位偏移限幅结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')
sys.path.insert(0, str(ROOT / 'test'))
sys.path.insert(0, str(ROOT / 'scripts/fpga'))
from open_fpga_synth import run_stage
from rtl_reference import read_rtl_source


def extract(text, prepare_thresholds=False):
    declarations = re.search(r'  logic \[\d+:0\] q_offset_low;.*?logic signed \[31:0\] q_clamped_data;',
                             text, re.S).group(0)
    arithmetic = re.search(r'  assign q_offset_low\s*=.*?(?=  assign ready)', text, re.S).group(0)
    if prepare_thresholds:
        preparation = re.search(r'  always_ff @\(posedge clk\) begin(.*?)\n  end', arithmetic, re.S)
        assignments = re.findall(r'(q_(?:minimum|maximum)_before_offset)\s*<=\s*(.*?);',
                                 preparation.group(1), re.S)
        if len(assignments) != 2:
            raise RuntimeError('未找到两个完整阈值计算表达式')
        replacement = '\n'.join('  assign ' + name + ' = ' + value + ';' for name, value in assignments)
        arithmetic = arithmetic[:preparation.start()] + replacement + arithmetic[preparation.end():]
    result = re.search(r'  assign q_clamped_data\s*=.*?;', text, re.S).group(0)
    return declarations + '\n' + arithmetic + result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='415a70a')
    parser.add_argument('--source', type=Path, default=ROOT / SOURCE)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = read_rtl_source(args.reference + ':' + str(SOURCE), cwd=ROOT, text=True)
    candidate = args.source.read_text()
    declarations = '''(
  input logic signed [63:0] q_rounded,
  input vector_engine_pkg::vector_engine_cfg_t c,
  output logic [33:0] o_result
);
'''
    units = []
    for name, body in [('reference', extract(reference)), ('candidate', extract(candidate, True))]:
        units.append('module ' + name + declarations + body +
                     '\nassign o_result = {q_above_max,q_below_min,q_clamped_data};\nendmodule\n')
    proof = out / 'threshold.sv'
    proof.write_text(''.join(units) + '''module threshold_proof (
  input logic signed [63:0] q_rounded,
  input vector_engine_pkg::vector_engine_cfg_t c,
  output logic equivalent
);
  logic [33:0] original, prepared;
  reference u_reference (.*,.o_result(original));
  candidate u_candidate (.*,.o_result(prepared));
  assign equivalent = original == prepared;
endmodule
''')
    sources = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv', proof]
    script = out / 'threshold.ys'
    script.write_text('read_slang --top threshold_proof ' + ' '.join(shlex.quote(str(p)) for p in sources) +
                      '\nprep -top threshold_proof -flatten\n' +
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    run = run_stage(script, out / 'threshold.log', dict(os.environ))
    if candidate != args.source.read_text():
        raise RuntimeError('验证期间生产源码发生变化')
    report = {'passed': True, 'inputs_constrained': False, 'relevant_input_bits': 160,
              'output_bits': 34, 'reference_revision': args.reference,
              'register_context': '阈值寄存器保存当前稳定配置的激活界限减输出偏移',
              'source_sha256': hashlib.sha256(candidate.encode()).hexdigest(),
              'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(), 'run': run}
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'output_bits': 34}))


if __name__ == '__main__':
    main()
