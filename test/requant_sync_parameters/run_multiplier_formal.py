#!/usr/bin/env python3
"""证明同步参数读周期与独立 DSP 输入寄存配合后的完整 INT32 乘法。"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rtl_reference import read_rtl_source

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('product_proof', ROOT / 'test/requant_product/run_formal.py')
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    relative = 'rtl/npu/conv/vector_scalar_multiplier.sv'
    reference = out / 'reference.sv'
    candidate = ROOT / relative
    four_dsp = 'p_cascade_mode' in candidate.read_text()
    if four_dsp:
        reference.write_bytes(candidate.read_bytes())
        reference_kind = 'current multiplier with AREG=1 and BREG=1'
        spec4 = importlib.util.spec_from_file_location('four_dsp', ROOT / 'test/requant_four_dsp/run_formal.py')
        proof4 = importlib.util.module_from_spec(spec4)
        spec4.loader.exec_module(proof4)
        proof.input_values = proof4.input_values
    else:
        reference.write_bytes(read_rtl_source('4ae43ade:' + relative, cwd=ROOT))
        reference_kind = '4ae43ade'
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    models = []
    for name in ('DSP48E1', 'FDRE'):
        model = re.search(r'^module ' + name + r'\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
        models.append(re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S))
    model_path = out / 'dsp48e1.sv'
    model_path.write_text('\n'.join(models) + '\n')

    def captures(module, label, use_dsp):
        nets = module['netnames']
        if not use_dsp:
            return [nets['u_product.operand_a']['bits'], nets['u_product.operand_b']['bits']]
        left = [nets[f'u_product.g_dsp.g_partial[{i}].u_multiply.u_dsp.Ar2']['bits'] for i in range(4)]
        right = [nets[f'u_product.g_dsp.g_partial[{i}].u_multiply.u_dsp.' +
                      ('Br2' if label == 'reference' else 'B')]['bits'] for i in range(4)]
        return left + right
    proof.capture_values = captures
    result = {'source_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
              'reference_kind': reference_kind, 'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
              'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
              'inputs_constrained': False, 'runs': []}
    for use_dsp in (0, 1):
        modules = {}
        for label, source in [('reference', reference), ('candidate', candidate)]:
            wrapper = out / f'{label}_dsp{use_dsp}.sv'
            capture = '' if label == 'reference' else '''logic signed [31:0] parameter_s0;
always_ff @(posedge clk) begin
    if (i_en) begin
        parameter_s0 <= i_b;
    end
end
'''
            parameters = f'.p_input_register(1), .p_use_dsp({use_dsp})'
            if label == 'candidate':
                parameters += ', .p_b_input_register(0)'
            b = 'i_b' if label == 'reference' else 'parameter_s0'
            wrapper.write_text('''module input_registered_product(
input logic clk, i_en,
input logic signed [31:0] i_a, i_b,
output logic signed [63:0] o_product
);
''' + capture + 'registered_multiplier_s32 #(' + parameters + ') u_product(\n'
                '.clk(clk), .i_en(i_en), .i_a(i_a), .i_b(' + b + '), .o_product(o_product));\nendmodule\n')
            stem = f'dsp{use_dsp}_{label}'
            code, log = proof.run_script(out, stem, ['read_verilog -formal -sv -D VERIFIC ' +
                ' '.join(shlex.quote(str(p)) for p in (source, wrapper, model_path)),
                'prep -top input_registered_product -flatten', 'wreduce', 'opt -full',
                'write_json ' + str(out / (stem + '.json'))])
            if code:
                raise RuntimeError(log[-12000:])
            modules[label] = json.loads((out / (stem + '.json')).read_text())['modules']['input_registered_product']
        for stage in ('input', 'arithmetic'):
            stem = f'dsp{use_dsp}_{stage}'
            commands = []
            for label in ('reference', 'candidate'):
                module, metadata = proof.stage_module(modules[label], label, use_dsp, stage)
                # 只保留相同采样时刻的比较点；右输入端口在两种存储位置之间相差一级。
                kept = set(module['ports'])
                if stage == 'arithmetic':
                    kept.update('u_product.' + name for name in (
                        'low_product', 'low_high_product', 'high_low_product', 'high_product',
                        'diagonal', 'low_high_extended', 'high_low_extended', 'upper_sum'))
                module['netnames'] = {
                    name if name in kept else f'$formal_{label}_{index}': value
                    for index, (name, value) in enumerate(module['netnames'].items())}
                module['attributes']['top'] = '1'
                path = out / (stem + '_' + label + '.json')
                path.write_text(json.dumps({'modules': {label: module}}))
                commands += ['read_json ' + str(path), 'wreduce', 'opt -full', 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate equivalent', 'hierarchy -top equivalent', 'opt_clean', 'opt_merge',
                         'equiv_simple -seq 2', 'equiv_induct -seq 2', 'equiv_status -assert']
            code, log = proof.run_script(out, stem, commands)
            if code or 'Equivalence successfully proven' not in log:
                raise RuntimeError(log[-12000:])
            item = {'use_dsp': use_dsp, 'stage': stage, 'passed': True,
                    'equivalent_bits': int(re.search(r'Of those cells (\d+) are proven', log)[1]),
                    'log_sha256': hashlib.sha256((out / (stem + '.log')).read_bytes()).hexdigest()}
            result['runs'].append(item)
            print(json.dumps(item), flush=True)
    result['passed'] = True
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
