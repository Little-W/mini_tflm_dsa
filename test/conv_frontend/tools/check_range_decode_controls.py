#!/usr/bin/env python3
"""验证组范围选择的综合表达式、任意候选数据及四态行为。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

import check_range_data_choice as selection

ROOT = Path(__file__).resolve().parents[3]
SOURCE = Path('rtl/npu/conv/conv_im2col_stream.sv')


def direct_model(text, name):
    value = selection.selection_module(text, name)
    if 'range_q_before_limit' in value:
        declaration = re.search(r'\blogic\s+range_q_before_limit\s*;', text)
        assignment = re.search(r'\bassign\s+range_q_before_limit\s*=[^;]+;', text)
        if declaration is None or assignment is None:
            raise RuntimeError('未找到实际范围比较表达式')
        value = value.replace(' logic range_decode_write,range_commit_context;',
                              ' logic range_decode_write,range_commit_context;\n ' +
                              declaration.group(0) + '\n ' + assignment.group(0))
    return value.replace('input logic [4:0] state_index', 'input logic [26:0] state_mask').replace(
        "assign i_state=27'b1<<state_index;", 'assign i_state=state_mask;')


def proof_model():
    ports = selection.PORTS.replace('input logic [4:0] state_index',
                                    'input logic [26:0] state_mask')
    return f'''module proof #(parameter int p_lanes=8,
 parameter bit p_register_descriptor=0,
 localparam int WIDTH=(p_lanes<=4?4:(1<<$clog2(p_lanes)))+1)(
{ports}, output logic equivalent,
 output logic [WIDTH-1:0] actual,expected,
 output logic actual_update,expected_update
);
 current #(.p_lanes(p_lanes),.p_register_descriptor(p_register_descriptor))
  u_current(.result(actual),.update_enable(actual_update),.*);
 reference #(.p_lanes(p_lanes),.p_register_descriptor(p_register_descriptor))
  u_reference(.result(expected),.update_enable(expected_update),.*);
`ifdef SYNTHESIS
 // 实际状态寄存器采用独热编码；未进入任何状态时也验证默认选择。
 always_comb assume($onehot0(state_mask));
`endif
 assign equivalent=actual_update==expected_update && actual==expected;
endmodule
'''


def four_state(lanes, descriptor):
    value = selection.four_state(lanes, descriptor)
    value = value.replace('logic [4:0] state_index', 'logic [26:0] state_mask')
    value = value.replace('state_index', 'state_mask')
    value = value.replace("state_mask=5'(sample%32);", "if(sample%4==0)state_mask=27'b1<<(sample%27);")
    value = value.replace('sample<65536', 'sample<8192').replace('checks=65536', 'checks=8192')
    value = value.replace('(actual_update && actual!==expected)', '(actual!==expected)')
    return value


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), stdout=stream, stderr=subprocess.STDOUT,
                       check=True, cwd=ROOT, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', default='2247144937c2fd04039b9b005151f371d6b51f8f')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = ROOT / SOURCE
    package = ROOT / 'rtl/npu/conv/conv_im2col_frontend_pkg.sv'
    helper = ROOT / 'rtl/common/onehot_mux.sv'
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in (path, package, helper)}
    original = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                       cwd=ROOT, text=True)
    model = out / 'model.sv'
    model.write_text(direct_model(path.read_text(), 'current') +
                     direct_model(original, 'reference') + proof_model())
    rows = []
    for descriptor in (0, 1):
        for lanes in (4, 8, 16):
            tag = f'lanes{lanes}_descriptor{descriptor}'
            script, log = out / (tag+'.ys'), out / (tag+'.log')
            script.write_text(f'read_slang --top proof -D SYNTHESIS=1 -Gp_lanes={lanes} '
                f'-Gp_register_descriptor={descriptor} ' +
                shlex.join(map(str, (package, helper, model))) +
                '\nprep -top proof -flatten\nchformal -lower\ncheck -assert\n' +
                'sat -set-def-inputs -set-assumes -verify -prove equivalent 1\n')
            run([sys.executable, ROOT / 'scripts/fpga/open_fpga_synth.py', '--worker', script], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in log.read_text():
                raise RuntimeError('组合等价证明未完成')
            tb, binary = out / (tag+'.sv'), out / (tag+'.vvp')
            tb.write_text(four_state(lanes, descriptor))
            run(['iverilog', '-g2012', '-s', 'tb', '-o', binary, package, helper, model, tb],
                out / (tag+'_build.log'))
            simulation = out / (tag+'_four_state.log')
            run(['vvp', binary], simulation)
            if 'PASS checks=8192' not in simulation.read_text():
                raise RuntimeError('四态比较未完成')
            rows.append(dict(lanes=lanes, register_descriptor=descriptor,
                             formal_passed=True, four_state_checks=8192))
            print('RANGE_DECODE_CONTROLS_PASS', lanes, descriptor, flush=True)
    if hashes != {str(p.relative_to(ROOT)): digest(p) for p in (path, package, helper)}:
        raise RuntimeError('验证期间源文件发生变化')
    summary = dict(passed=True, reference=args.reference, source_sha256=hashes,
                   formal_input_assumptions=['Operation state is one-hot or zero'],
                   four_state_input_assumptions=[],
                   compared_outputs='All range values and update enables',
                   state_bits=27, source_candidates='Independent arbitrary values', cases=rows)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')


if __name__ == '__main__':
    main()
