#!/usr/bin/env python3
"""分阶段证明共享 INT32 乘法器的输入寄存、完整乘积及任意流水暂停。"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def input_values(a, b):
    return ([a[:16] + ['0'] * 14, a[:16] + ['0'] * 14,
             a[16:] + [a[31]] * 14, a[16:] + [a[31]] * 14] +
            [b[:16] + ['0'] * 2, b[16:] + [b[31]] * 2,
             b[:16] + ['0'] * 2, b[16:] + [b[31]] * 2])


def capture_values(module, label, use_dsp):
    nets = module['netnames']
    if label == 'reference':
        a, b = [nets[name]['bits'] for name in ('captured_a', 'captured_b')]
        return input_values(a, b) if use_dsp else [a, b]
    if not use_dsp:
        return [nets[name]['bits'] for name in ('operand_a', 'operand_b')]
    return [nets[f'g_dsp.g_partial[{i}].u_multiply.u_dsp.{register}']['bits']
            for register in ('Ar2', 'Br2') for i in range(4)]


def stage_module(original, label, use_dsp, stage):
    module = copy.deepcopy(original)
    if stage == 'input':
        bits = sum(capture_values(module, label, use_dsp), [])
        module['ports'] = {name: port for name, port in module['ports'].items() if port['direction'] != 'output'}
        module['ports']['o_capture'] = {'direction': 'output', 'bits': bits}
        module['netnames']['o_capture'] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
        for net in module['netnames'].values():
            net['attributes'].pop('keep', None)
        return module, {'capture_bits_compared': len(bits)}
    all_bits = [bit for net in module['netnames'].values() for bit in net['bits'] if isinstance(bit, int)]
    first = max(all_bits) + 1
    a, b = list(range(first, first + 32)), list(range(first + 32, first + 64))
    actual = capture_values(module, label, use_dsp)
    expected = input_values(a, b) if use_dsp else [a, b]
    mapping = {}
    for captured, abstract in zip(actual, expected):
        assert len(captured) == len(abstract)
        for old, new in zip(captured, abstract):
            if isinstance(old, int):
                assert old not in mapping or mapping[old] == new
                mapping[old] = new
            else:
                assert old == new
    primary_bits = {bit for port in module['ports'].values() if port['direction'] == 'input' for bit in port['bits']}
    assert not (set(mapping) & primary_bits)
    removed = set()
    for name, cell in list(module['cells'].items()):
        qbits = cell['connections'].get('Q', []) if 'dff' in cell['type'] else []
        if any(bit in mapping for bit in qbits):
            assert all(bit in mapping for bit in qbits)
            removed.update(qbits)
            del module['cells'][name]
    assert removed == set(mapping), (len(removed), len(mapping))
    for cell in module['cells'].values():
        for port, bits in cell['connections'].items():
            cell['connections'][port] = [mapping.get(bit, bit) for bit in bits]
    for net in module['netnames'].values():
        if any(bit in mapping for bit in net['bits']):
            net['attributes'].pop('init', None)
        net['bits'] = [mapping.get(bit, bit) for bit in net['bits']]
    for port in module['ports'].values():
        port['bits'] = [mapping.get(bit, bit) for bit in port['bits']]
    for name, bits in [('captured_a', a), ('captured_b', b)]:
        module['ports'][name] = {'direction': 'input', 'bits': bits}
        module['netnames'][name] = {'hide_name': 0, 'bits': bits, 'attributes': {}}
    return module, {'proven_input_register_bits_abstracted': len(removed)}


def run_script(out, stem, commands):
    script = out / (stem + '.ys')
    script.write_text('\n'.join(commands) + '\n')
    log_path = out / (stem + '.log')
    with log_path.open('w') as stream:
        result = subprocess.run([sys.executable, __file__, '--out', str(out), '--worker', str(script)],
                                stdout=stream, stderr=subprocess.STDOUT)
    return result.returncode, log_path.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--generic-only', action='store_true')
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/conv/vector_scalar_multiplier.sv'
    old = subprocess.check_output(
        ['git', 'show', 'b8b34d5:rtl/npu/conv/vector_scalar_multiplier.sv'], cwd=ROOT, text=True)
    reference = old.replace('module vector_scalar_multiplier (', 'module enabled_reference (')
    reference = reference.replace('  input  wire logic clk,', '  input  wire logic clk,\n  input logic i_en,')
    for old_name, new_name in [('a', 'i_a'), ('b', 'i_b'), ('product', 'o_product')]:
        reference = re.sub(r'\b' + old_name + r'\b', new_name, reference)
    reference, count = re.subn(
        r'(  always_ff @\(posedge clk\) begin\n)(.*?)(  end\n)',
        lambda match: match[1] + '    if (i_en) begin\n' + match[2] + '    end\n' + match[3],
        reference, flags=re.S)
    assert count == 2
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S)[0]
    model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S)
    model_path = out / 'dsp48e1.sv'
    model_path.write_text(model + '\n')
    summary = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'reference_rev': 'b8b34d5', 'reference_sha256': hashlib.sha256(old.encode()).hexdigest(),
               'primitive_library_sha256': hashlib.sha256(library.read_bytes()).hexdigest(),
               'enabled_edges': '2 + p_input_register', 'clock_enable': 'unconstrained each cycle',
               'method': 'Input storage is proved before its corresponding signals become common arithmetic inputs.',
               'runs': []}
    four_dsp = 'p_cascade_mode' in source.read_text()
    for input_register, use_dsp in ((0, 0), (0, 1), (1, 0), (1, 1)):
        if use_dsp and (four_dsp or args.generic_only):
            continue
        selected_reference = reference
        if input_register:
            extra = ('logic signed [31:0] captured_a, captured_b;\n'
                     'always_ff @(posedge clk) if (i_en) begin captured_a <= i_a; captured_b <= i_b; end\n')
            selected_reference = selected_reference.replace('  //! 0. Helper', extra + '  //! 0. Helper')
            for name in ('low_product', 'low_high_product', 'high_low_product', 'high_product'):
                match = re.search(r'\b' + name + r'\s*<=.*?;', selected_reference, re.S)[0]
                selected_reference = selected_reference.replace(
                    match, match.replace('i_a[', 'captured_a[').replace('i_b[', 'captured_b['))
        reference_path = out / f'reference_input{input_register}.sv'
        reference_path.write_text(selected_reference)
        modules = {}
        for label, top, path in [('reference', 'enabled_reference', reference_path),
                                 ('candidate', 'registered_multiplier_s32', source)]:
            stem = f'input{input_register}_dsp{use_dsp}_{label}'
            commands = ['read_verilog -formal -sv -D VERIFIC ' +
                        ' '.join(shlex.quote(str(p)) for p in (path, model_path))]
            if label == 'candidate':
                commands += [f'chparam -set p_use_dsp {use_dsp} -set p_input_register {input_register} {top}']
            commands += ['prep -top ' + top + ' -flatten', 'wreduce', 'opt -full']
            if label == 'candidate' and not use_dsp and four_dsp:
                commands += ['cd ' + top]
                for name in ('low_product', 'low_high_product', 'high_low_product', 'high_product', 'diagonal'):
                    commands += ['rename g_generic.' + name + ' ' + name]
                commands += ['cd ..']
            commands += ['write_json ' + str(out / (stem + '.json'))]
            code, log = run_script(out, stem, commands)
            if code:
                raise RuntimeError(log[-5000:])
            flattened = json.loads((out / (stem + '.json')).read_text())['modules']
            assert len(flattened) == 1
            modules[label] = next(iter(flattened.values()))
        stages = ('input', 'arithmetic') if input_register else ('arithmetic',)
        for stage in stages:
            stem = f'input{input_register}_dsp{use_dsp}_{stage}'
            commands, modifications = [], {}
            for label in ('reference', 'candidate'):
                module = modules[label]
                if input_register:
                    module, modifications[label] = stage_module(module, label, use_dsp, stage)
                module['attributes']['top'] = '1'
                path = out / (stem + '_' + label + '.json')
                path.write_text(json.dumps({'modules': {label: module}}))
                commands += ['read_json ' + str(path), 'opt_clean', 'design -stash ' + label]
            commands += ['design -copy-from reference -as reference reference',
                         'design -copy-from candidate -as candidate candidate',
                         'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                         'equiv_simple -seq 2', 'equiv_induct -seq 2', 'equiv_status -assert']
            code, log = run_script(out, stem, commands)
            bits = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', log)
            record = {'p_input_register': input_register, 'p_use_dsp': use_dsp, 'stage': stage,
                      'passed': code == 0 and 'Equivalence successfully proven' in log,
                      'equivalent_bits': int(bits[1]) if bits else None, 'stage_mapping': modifications}
            summary['runs'].append(record)
            print(json.dumps(record), flush=True)
            if not record['passed']:
                raise RuntimeError(log[-10000:])
    if four_dsp and not args.generic_only:
        spec = importlib.util.spec_from_file_location('four_dsp', ROOT / 'test/requant_four_dsp/run_formal.py')
        proof = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proof)
        summary['four_dsp'] = proof.run_formal(source, out / 'four_dsp')
    summary['passed'] = all(record['passed'] for record in summary['runs'])
    summary['passed'] &= summary.get('four_dsp', {'passed': True})['passed']
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
