#!/usr/bin/env python3
"""检查帧地址流水线的符号部分积、分段算术与分块地址表达式。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/top/frame_address_prepare.sv'
    helper = ROOT / 'rtl/common/parallel_prefix_add.sv'
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    helper_hash = hashlib.sha256(helper.read_bytes()).hexdigest()
    def run(name: str, commands: list[str], timeout: int = 180) -> str:
        script = out / (name + '.ys')
        script.write_text('\n'.join(commands) + '\n')
        log = out / (name + '.log')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                    cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        if result.returncode:
            raise RuntimeError(log.read_text()[-12000:])
        return log.read_text()

    ports = re.search(r'\) \(\n(.*?)\n\);', source.read_text(), re.S)[1]
    declarations = [line.strip().rstrip(',') for line in ports.splitlines() if 'input ' in line]
    input_names = re.findall(r'input\s+(?:wire\s+)?logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
    output_names = re.findall(r'output\s+(?:wire\s+)?logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
    symbolic = out / 'symbolic_frame_address.sv'
    body = source.read_text().replace('module frame_address_prepare #(', 'module symbolic_frame_address #(', 1)
    body = body.replace('input  wire logic clk,', 'input wire logic [33:0] formal_partial_product,\n    input  wire logic clk,', 1)
    product_expression = 'assign partial_product = multiply_a * multiply_b;'
    if body.count(product_expression) != 1:
        raise RuntimeError('Expected one shared partial-product expression')
    body = body.replace(product_expression, 'assign partial_product = formal_partial_product;', 1)
    symbolic.write_text(body)
    miter = out / 'pipeline_miter.sv'
    text = 'module pipeline_miter(\n' + ',\n'.join(declarations + ['input logic [33:0] product']) + '\n);\n'
    for name in output_names:
        width = '[31:0] ' if name.endswith('_base') else ''
        text += 'wire ' + width + name + '_0, ' + name + '_1;\n'
    text += 'wire start = i_start && o_start_rdy_0 && o_start_rdy_1;\n'
    text += 'wire consume = i_result_rdy && o_result_vld_0 && o_result_vld_1;\n'
    for stage in (0, 1):
        connections = ['.formal_partial_product(product)']
        for name in input_names:
            value = 'start' if name == 'i_start' else ('consume' if name == 'i_result_rdy' else name)
            connections.append('.' + name + '(' + value + ')')
        connections += ['.' + name + '(' + name + '_' + str(stage) + ')' for name in output_names]
        text += 'symbolic_frame_address #(.p_pipeline_products(' + str(stage) + ')) u_' + str(stage) + '(' + ','.join(connections) + ');\n'
    text += 'always @(posedge clk) if (rst_n && o_result_vld_1) begin\n'
    text += '    assert(o_result_vld_0);\n'
    for name in output_names:
        if name.endswith('_base'):
            text += '    assert(' + name + '_0 == ' + name + '_1);\n'
    text += 'end\nendmodule\n'
    miter.write_text(text)
    pipeline_log = run('pipeline', [
        'read_slang --top pipeline_miter -DASIC_SYNTHESIS=1 ' + ' '.join(map(str, (symbolic, helper, miter))),
        'prep -top pipeline_miter -flatten', 'memory_map', 'async2sync', 'chformal -lower', 'opt -full',
        'sat -verify -prove-asserts -seq 28 -set-at 1 rst_n 0 -set-def-inputs -show-inputs',
    ], timeout=240)
    if 'SAT proof finished - no model found: SUCCESS!' not in pipeline_log:
        raise RuntimeError('Incomplete pipeline comparison')
    summary = {'source_sha256': source_hash, 'helper_sha256': helper_hash,
               'pipeline': {'passed': True, 'bounded_cycles': 28, 'reset_at_first_cycle': True,
                            'partial_product_symbolic': True, 'abort_unconstrained': True,
                            'result_ready_unconstrained': True, 'compared_result_bits': 96},
               'address_forms': []}
    print('pipeline', summary['pipeline'], flush=True)

    arithmetic = out / 'arithmetic.sv'
    arithmetic.write_text('''module address_arithmetic_formal(
    input logic [33:0] i_low,
    input logic signed [31:0] i_cross_a, i_cross_b,
    input logic [31:0] i_addend
);
    logic signed [47:0] first_sum, second_sum, third_sum;
    logic [31:0] expected, actual;
    logic [31:0] narrow_first, narrow_second, narrow_third, narrow_actual;
    assign first_sum = $signed({14'd0,i_low}) + $signed({16'd0,i_addend});
    assign second_sum = (first_sum >>> 17) + 48'(i_cross_a);
    assign third_sum = second_sum + 48'(i_cross_b);
    assign actual = {third_sum[14:0],first_sum[16:0]};
    assign expected = i_low[31:0] + (32'(i_cross_a) << 17) + (32'(i_cross_b) << 17) + i_addend;
    assign narrow_first = i_low[31:0] + i_addend;
    assign narrow_second = i_cross_a + {17'd0,narrow_first[31:17]};
    assign narrow_third = narrow_second + i_cross_b;
    assign narrow_actual = {narrow_third[14:0],narrow_first[16:0]};
    always_comb begin
        assert(actual == expected);
        assert(narrow_actual == expected);
    end
endmodule
''')
    text = run('arithmetic', ['read_slang --top address_arithmetic_formal ' + str(arithmetic),
        'prep -top address_arithmetic_formal -flatten', 'chformal -lower', 'opt -full',
        'sat -verify -prove-asserts -show-inputs'])
    assert 'SAT proof finished - no model found: SUCCESS!' in text
    summary['arithmetic'] = {'passed': True, 'independent_partial_and_addend_bits': 130}
    print('arithmetic', summary['arithmetic'], flush=True)

    # 整数多项式恒等式验证十七位拆分；地址只保留模 2^32 的结果。
    from sympy import expand, symbols
    al, ah, bl, bh = symbols('al ah bl bh', integer=True)
    assert expand((al + (1 << 17)*ah)*(bl + (1 << 17)*bh) -
                  (al*bl + (1 << 17)*(al*bh + ah*bl) + (1 << 34)*ah*bh)) == 0
    assert (1 << 34) % (1 << 32) == 0
    summary['integer_product_identity'] = {'passed': True, 'low_width': 17,
                                         'high_width': 15, 'address_modulus': 1 << 32}
    row, tiles, depth, low, scale, element = symbols('row tiles depth low scale element', integer=True)
    assert expand(((row*tiles + depth)*scale + low)*element -
                  ((row*scale*element)*tiles + (depth*scale + low)*element)) == 0
    summary['packed_product_identity'] = {'passed': True, 'ring': 'integers modulo 2^32'}

    for size in (1, 2, 4, 8, 16, 32):
        shift = size.bit_length() - 1
        form = out / f'address_form_{size}.sv'
        form.write_text(f'''module address_form_formal(
    input logic [31:0] i_row, i_q, i_product, i_base,
    input logic i_packed, i_s16
);
    localparam int SHIFT={shift};
    logic [31:0] old_elements, old_offset;
    logic [31:0] scaled_product,residual,new_address,old_address;
    assign old_elements = ((i_product + (i_q >> SHIFT)) << (2*SHIFT)) + ((i_row & 32'd{size-1}) << SHIFT);
    assign old_offset = i_packed ? (old_elements << i_s16) : (i_product + (i_q << i_s16));
    assign old_address = i_base + old_offset;
    assign scaled_product = i_packed ? (i_product << (2*SHIFT + int'(i_s16))) : i_product;
    assign residual = i_packed ? ((((i_q >> SHIFT) << (2*SHIFT)) | ((i_row & 32'd{size-1}) << SHIFT)) << i_s16) : (i_q << i_s16);
    assign new_address = scaled_product + i_base + residual;
    always_comb assert(new_address == old_address);
endmodule
''')
        text = run(f'address_form_{size}', ['read_slang --top address_form_formal ' + str(form),
            'prep -top address_form_formal -flatten', 'chformal -lower', 'wreduce', 'opt -full',
            'techmap', 'opt -full', 'sat -verify -prove-asserts -show-inputs'], timeout=180)
        assert 'SAT proof finished - no model found: SUCCESS!' in text
        summary['address_forms'].append({'size': size, 'input_bits': 130,
                                         'product_unconstrained': True, 'passed': True})
        print('address_form', size, 'PASS', flush=True)

    if source_hash != hashlib.sha256(source.read_bytes()).hexdigest():
        raise RuntimeError('RTL changed during formal verification')
    if helper_hash != hashlib.sha256(helper.read_bytes()).hexdigest():
        raise RuntimeError('Adder changed during formal verification')
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
