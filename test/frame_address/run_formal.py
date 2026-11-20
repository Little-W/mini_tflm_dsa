#!/usr/bin/env python3
"""证明帧地址准备的原语状态、分段乘加与分块地址表达式。"""
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
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model_file = out / 'dsp48e1.sv'
    model_file.write_text(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S) + '\n')

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
    names = re.findall(r'(?:input|output)\s+logic\s*(?:\[[^]]+\]\s*)?(\w+)', ports)
    connections = ',\n'.join('.' + name + '(' + name + ')' for name in names)
    commands = []
    for label, dsp in [('reference', 0), ('candidate', 1)]:
        wrapper = out / (label + '.sv')
        wrapper.write_text(f'module {label}(\n{ports}\n);\n'
                           f'frame_address_prepare #(.p_size(16),.p_use_dsp({dsp})) u_impl (\n{connections}\n);\nendmodule\n')
        commands += [
            'read_slang --top ' + label + ' -D VERIFIC --blackboxed-module DSP48E1 -v ' +
            shlex.quote(str(model_file)) + ' ' + ' '.join(shlex.quote(str(p)) for p in (source, wrapper)),
            'read_verilog -formal -sv -D VERIFIC -overwrite ' + shlex.quote(str(model_file)),
            'prep -top ' + label + ' -flatten', 'memory_map', 'wreduce', 'opt -full', 'async2sync', 'opt -full',
            'write_json ' + shlex.quote(str(out / (label + '_flat.json'))),
            'design -stash ' + label,
        ]
    run('elaborate', commands)
    commands = []
    for label, product_name in [('reference', 'u_impl.g_generic.partial_product'),
                                ('candidate', 'u_impl.g_dsp.u_dsp.M')]:
        path = out / (label + '_flat.json')
        design = json.loads(path.read_text())
        module = design['modules'][label]
        product = module['netnames'][product_name]['bits']
        if len(product) > 36:
            assert all(bit == product[35] for bit in product[36:])
        module['netnames']['formal_partial_product'] = {'hide_name': 0, 'bits': product[:36], 'attributes': {}}
        path = out / (label + '_named.json')
        path.write_text(json.dumps(design))
        commands += ['read_json ' + shlex.quote(str(path)), 'design -stash ' + label]
    commands += [
        'design -copy-from reference -as reference reference',
        'design -copy-from candidate -as candidate candidate',
        'equiv_make reference candidate equiv', 'hierarchy -top equiv', 'opt -full',
        'equiv_simple -seq 2', 'equiv_induct -seq 2', 'equiv_status -assert',
    ]
    state_log = run('primitive_state', commands)
    if 'Equivalence successfully proven' not in state_log:
        raise RuntimeError('Incomplete primitive state proof')
    summary = {'source_sha256': source_hash,
               'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
               'inputs_constrained': False, 'abort_constrained': False, 'result_ready_constrained': False,
               'primitive_state': {'passed': True, 'equivalent_bits': int(re.search(
                   r'Of those cells (\d+) are proven', state_log)[1])}, 'address_forms': []}
    print('primitive_state', summary['primitive_state'], flush=True)

    arithmetic = out / 'arithmetic.sv'
    arithmetic.write_text('''module address_arithmetic_formal(
    input logic [33:0] i_low,
    input logic signed [31:0] i_cross_a, i_cross_b,
    input logic [31:0] i_addend
);
    logic signed [47:0] first_sum, second_sum, third_sum;
    logic [31:0] expected, actual;
    assign first_sum = $signed({14'd0,i_low}) + $signed({16'd0,i_addend});
    assign second_sum = (first_sum >>> 17) + 48'(i_cross_a);
    assign third_sum = second_sum + 48'(i_cross_b);
    assign actual = {third_sum[14:0],first_sum[16:0]};
    assign expected = i_low[31:0] + (32'(i_cross_a) << 17) + (32'(i_cross_b) << 17) + i_addend;
    always_comb assert(actual == expected);
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
    summary['passed'] = True
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
