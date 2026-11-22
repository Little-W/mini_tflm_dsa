#!/usr/bin/env python3
"""证明定宽加法的全部输入，并生成带输入和输出寄存器的普通 RTL 测量电路。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'rtl/common/parallel_prefix_add.sv'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--asic', action='store_true', help='使用 ASIC 编译配置')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    formal = out / 'formal.sv'
    formal.write_text('''module prefix_add_formal #(
    parameter int p_width=32,
    parameter int p_group_width=8,
    parameter bit p_preserve_groups=1'b0
) (
    input logic [p_width-1:0] i_a, i_b,
    input logic i_carry,
    output logic o_equal
);
    logic [p_width-1:0] sum;
    logic carry;
    parallel_prefix_add #(.p_width(p_width), .p_group_width(p_group_width),
        .p_preserve_groups(p_preserve_groups)) u_add (
        .*, .o_sum(sum), .o_carry(carry));
    assign o_equal = {carry, sum} == ({1'b0,i_a} + {1'b0,i_b} + i_carry);
endmodule
''')
    report = {'inputs_constrained': False, 'latency_cycles': 0, 'asic': args.asic,
              'source_sha256': hashlib.sha256(RTL.read_bytes()).hexdigest(), 'runs': []}
    for width, group, preserve in ((width, group, preserve)
            for width in (1, 2, 3, 4, 5, 8, 17, 23, 24, 32, 33, 47, 48, 64)
            for group, preserve in ((1, 0), (8, 1))):
        folder = out / f'w{width}_group{group}_preserve{preserve}'
        folder.mkdir(exist_ok=True)
        script, log = folder / 'run.ys', folder / 'formal.log'
        defines = '-DASIC_SYNTHESIS=1 ' if args.asic else ''
        script.write_text(f'read_slang --top prefix_add_formal {defines}-Gp_width={width} ' +
                          f'-Gp_group_width={group} -Gp_preserve_groups={preserve} ' +
                          shlex.join(map(str, (RTL, formal))) + '\n' +
                          'prep -top prefix_add_formal -flatten\ncheck -assert\n' +
                          'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], stdout=stream,
                           stderr=subprocess.STDOUT, timeout=180, check=True)
        passed = 'SAT proof finished - no model found: SUCCESS!' in log.read_text()
        if not passed:
            raise RuntimeError(f'Proof did not complete: {log}')
        report['runs'].append(dict(width=width, group_width=group, preserve_groups=bool(preserve),
                                  passed=True, input_bits=2*width+1))
        print(f'width={width} group_width={group} preserve_groups={preserve}: PASS', flush=True)
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    measure = out / 'measure.sv'
    measure.write_text('''module add_measure #(
    parameter int p_width=32,
    parameter bit p_prefix=1'b1
) (
    input logic clk,
    input logic [p_width-1:0] i_a, i_b,
    input logic i_carry,
    output logic [p_width:0] o_result
);
    logic [p_width-1:0] a, b, sum;
    logic carry_in, carry_out;
    always_ff @(posedge clk) begin
        a <= i_a;
        b <= i_b;
        carry_in <= i_carry;
        o_result <= {carry_out, sum};
    end
    if (p_prefix) begin : g_prefix
        parallel_prefix_add #(.p_width(p_width)) u_add (
            .i_a(a), .i_b(b), .i_carry(carry_in), .o_sum(sum), .o_carry(carry_out));
    end else begin : g_reference
        assign {carry_out, sum} = {1'b0, a} + {1'b0, b} + carry_in;
    end
endmodule
''')
    cases = {}
    for width in (32, 64):
        for prefix in (0, 1):
            cases[f'w{width}_prefix{prefix}'] = dict(
                top='add_measure', options=[f'-Gp_width={width}', f'-Gp_prefix={prefix}', '-D', 'SYNTHESIS=1'],
                sources=[str(RTL), str(measure)], configuration=f'{width}-bit registered addition with carry input/output')
    (out / 'cases.json').write_text(json.dumps(cases, indent=2) + '\n')


if __name__ == '__main__':
    main()
