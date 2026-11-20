#!/usr/bin/env python3
"""证明向量写回地址共享保持全部状态和地址输入的结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/conv/vector_engine.sv')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(text):
    return re.sub(r'\s+', '', re.sub(r'/\*.*?\*/|//[^\n]*', '', text, flags=re.S))


def address_cases(text):
    states = list(re.finditer(r'^        ([A-Z_]+):', text, re.M))
    result = {}
    for index, state in enumerate(states):
        end = states[index + 1].start() if index + 1 < len(states) else len(text)
        assignments = re.findall(r'write_origin\s*<=([^;]+);', text[state.end():end])
        if assignments:
            if len(assignments) != 1:
                raise RuntimeError('Unexpected address assignment count')
            result[state.group(1)] = assignments[0].strip()
    return result


def unit(ports, enums, body, expression):
    return f'''module vector_write_address_decode({ports}, input logic i_commit,
output logic [31:0] o_address);
import vector_engine_pkg::*;
{enums}
{body}
always_ff @(posedge clk) if (i_commit) o_address <= {expression};
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='67c25118')
    parser.add_argument('--mapped-case', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (ROOT / SOURCE).read_text()
    revision = subprocess.check_output(['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip()
    reference = subprocess.check_output(['git', 'show', f'{revision}:{SOURCE}'], cwd=ROOT, text=True)
    first = current.index('  // 写回状态选择完整偏移，公共加法器生成最终输出地址。')
    last = current.index('  wire signed [15:0] input_lane [PE_COUNT];', first)
    fragment = current[first:last]
    remainder = current[:first] + current[last:]
    old_assignments = re.findall(r'write_origin\s*<=([^;]+);', reference)
    new_assignments = re.findall(r'write_origin\s*<=([^;]+);', remainder)
    if len(old_assignments) != len(new_assignments):
        raise RuntimeError('Address update count differs')
    for old, new in zip(old_assignments, new_assignments):
        if new.strip() not in ('write_origin_next', old.strip()):
            raise RuntimeError('Unexpected write address expression')
    iterator = iter(old_assignments)
    restored = re.sub(r'(write_origin\s*<=)([^;]+)(;)',
                      lambda match: match.group(1) + next(iterator) + match.group(3), remainder)
    if normalized(restored) != normalized(reference):
        raise RuntimeError('Logic outside the address expressions differs')
    old_cases = address_cases(reference)
    new_cases = address_cases(current)
    expected_states = {'EXECUTE_COMMIT', 'ADD_STORE', 'QUANT_STREAM', 'AVG_POWER_STORE',
                       'AVG_WAIT', 'POOL_STORE', 'SOFT_RUN', 'VECTOR_REDUCE'}
    if old_cases.keys() != expected_states or new_cases.keys() != expected_states:
        raise RuntimeError('Address update state coverage differs')
    if any(value != 'write_origin_next' for value in new_cases.values()):
        raise RuntimeError('Shared address is not used in every update state')
    enums = re.search(r'  typedef enum logic \[5:0\].*?} state_t;', current, re.S).group()
    expected = 'always_comb begin\nexpected = c.output_base;\ncase (state)\n' + ''.join(
        f'{state}: expected = {expression};\n' for state, expression in old_cases.items()
    ) + 'default: begin end\nendcase\nend\n'
    ports = '''input logic clk,input logic [5:0] state,
input vector_engine_pkg::vector_engine_cfg_t c,
input logic [31:0] vector_offset,position_offset,input logic [15:0] channel_base'''
    proof = out / 'proof.sv'
    proof.write_text(f'''module address_proof({ports}, output logic equivalent);
import vector_engine_pkg::*;
{enums}
{fragment}
logic [31:0] expected;
{expected}
assign equivalent = write_origin_next == expected;
endmodule
''')
    import pyosys
    library = Path(pyosys.__file__).parent / 'share/xilinx/cells_sim.v'
    model = re.search(r'^module DSP48E1\b.*?^endmodule', library.read_text(), re.M | re.S).group()
    model = re.sub(r'\bspecify\b.*?\bendspecify\b', '', model, flags=re.S)
    model_file = out / 'primitive_models.sv'
    model_file.write_text(model + '\n')
    packages = [ROOT / 'rtl/npu/conv/conv_im2col_pkg.sv', ROOT / 'rtl/npu/conv/vector_engine_pkg.sv']
    sources = [ROOT / SOURCE, *packages, Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): sha(path) for path in sources}
    checks = []
    for mode in ('rtl',):
        script = out / f'{mode}.ys'
        quoted = ' '.join(shlex.quote(str(path)) for path in [*packages, proof])
        script.write_text(f'read_slang -D SYNTHESIS=1 '
                          f'--top address_proof {quoted}\nprep -top address_proof -flatten\n'
                          'opt -full\nsat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        log = out / f'{mode}.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        if result.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(log.read_text()[-6000:])
        checks.append({'mode': mode, 'passed': True, 'log_sha256': sha(log)})
    if args.mapped_case:
        folder = args.mapped_case.resolve()
        top = 'vector_write_address_decode'
        manifest = json.loads((folder / 'manifest.json').read_text())
        expected_source_sha = hashlib.sha256(unit(ports, enums, fragment, 'write_origin_next').encode()).hexdigest()
        if manifest['sources_sha256'].get(str(out / 'current.sv')) != expected_source_sha:
            raise RuntimeError('Mapped source differs from the current address expressions')
        helper = ROOT / 'scripts/fpga/techmap/wide_alu_dsp.sv'
        commands = []
        for label, filename in (('reference', 'pre_alu.json'), ('current', 'mapped_alu.json')):
            commands.append('read_json ' + shlex.quote(str(folder / filename)))
            if label == 'current':
                commands.extend(['read_rtlil ' + shlex.quote(str(folder / 'mapped_alu.autoidx.il')),
                                 'verilog_defaults -push', 'verilog_defaults -add -sv',
                                 'techmap -map ' + shlex.quote(str(helper)), 'verilog_defaults -pop'])
            commands.extend(['read_verilog -sv -D VERIFIC ' + shlex.quote(str(model_file)),
                             f'prep -top {top} -flatten', f'rename {top} {label}',
                             'design -stash ' + label])
        commands.extend(['design -copy-from reference -as reference reference',
                         'design -copy-from current -as current current',
                         'miter -equiv -make_assert reference current comparison',
                         'prep -top comparison -flatten', 'chformal -lower', 'opt -full',
                         'sat -seq 2 -set-at 1 trigger 0 -prove-skip 1 -prove-asserts '
                         '-verify -set-def-inputs -show-inputs -show-outputs'])
        script = out / 'mapped.ys'
        script.write_text('\n'.join(commands) + '\n')
        log = out / 'mapped.log'
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                     '--worker', str(script)], cwd=ROOT, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=180)
        if result.returncode or 'SUCCESS!' not in log.read_text():
            raise RuntimeError(log.read_text()[-6000:])
        checks.append({'mode': 'mapped_dsp', 'passed': True, 'log_sha256': sha(log),
                       'input_json_sha256': sha(folder / 'pre_alu.json'),
                       'mapped_json_sha256': sha(folder / 'mapped_alu.json'),
                       'mapped_source_sha256': expected_source_sha,
                       'helper_sha256': sha(helper),
                       'initial_relation': '两份任意且相同的32位地址寄存器内容'})
    cases = {}
    for label in ('reference', 'current'):
        body = 'logic [31:0] expected;\n' + expected if label == 'reference' else fragment
        expression = 'expected' if label == 'reference' else 'write_origin_next'
        path = out / f'{label}.sv'
        path.write_text(unit(ports, enums, body, expression))
        cases[label] = {'top': 'vector_write_address_decode', 'options': ['-D', 'SYNTHESIS=1'],
                        'sources': [str(item) for item in [*packages, path]],
                        'configuration': '完整状态译码、112位地址输入和32位输出寄存器'}
    (out / 'cases.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2) + '\n')
    reference_path = out / 'vector_engine_reference.sv'
    reference_path.write_text(reference)
    reference_checker = out / 'vector_config_check_reference.sv'
    reference_checker.write_bytes(subprocess.check_output(
        ['git', 'show', f'{revision}:rtl/npu/conv/vector_config_check.sv'], cwd=ROOT))
    vector_sources = [ROOT / 'rtl/npu/conv' / name for name in (
        'conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_config_check.sv',
        'vector_writeback.sv', 'vector_round_shift.sv', 'vector_scalar_multiplier.sv',
        'vector_pe.sv', 'vector_softmax.sv', 'vector_quant_params.sv')]
    vector_cases = {}
    for label, path in (('reference', reference_path), ('current', ROOT / SOURCE)):
        vector_cases[label] = {'top': 'vector_engine',
            'options': ['-D', 'SYNTHESIS=1', '-GTILE=16', '-GBUS_WIDTH=64', '-GPE_COUNT=8'],
            'sources': [str(reference_checker) if label == 'reference' and
                        item.name == 'vector_config_check.sv' else str(item)
                        for item in [*vector_sources, path]],
            'configuration': 'TILE16 BUS64 PE8 完整向量引擎'}
    (out / 'vector_cases.json').write_text(json.dumps(vector_cases, ensure_ascii=False, indent=2) + '\n')
    if hashes != {str(path.relative_to(ROOT)): sha(path) for path in sources}:
        raise RuntimeError('Source files changed during verification')
    report = {
        'passed': True, 'reference_commit': revision, 'source_sha256': hashes,
        'reference_engine_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'primitive_library_sha256': sha(library), 'proof_sha256': sha(proof),
        'actual_source_expressions': True, 'other_logic_unchanged': True,
        'register_update_conditions_unchanged': True, 'update_states': sorted(old_cases),
        'input_constraints': None, 'address_input_bits': 112, 'compared_address_bits': 32,
        'compared_state_values': 64, 'checks': checks,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'modes': len(checks), 'update_states': len(old_cases)}))


if __name__ == '__main__':
    main()
