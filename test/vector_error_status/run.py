#!/usr/bin/env python3
"""验证向量错误状态的完整控制输出、错误优先级与四态传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

from pyslang.syntax import SyntaxTree

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = '59a1e9f3'
CONTROL = ROOT / 'rtl/npu/conv/vector_engine_control.sv'
SELECT = ROOT / 'rtl/npu/conv/vector_engine_error_select.sv'
PACKAGES = [ROOT / 'rtl/npu/conv' / name for name in
            ('conv_im2col_pkg.sv', 'vector_engine_pkg.sv', 'vector_engine_control_pkg.sv')]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, check=True, stdout=stream,
                       stderr=subprocess.STDOUT, timeout=300)


def error_statements(node, indent=2):
    """从完整控制过程提取错误赋值，并保留包围赋值的条件及分支顺序。"""
    pad = '  ' * indent
    kind = node.kind.name
    if kind == 'ExpressionStatement':
        value = str(node).strip()
        if not re.match(r'error\s*<=', value):
            return ''
        return pad + re.sub(r'^error\s*<=', 'expected =', value)
    if kind == 'SequentialBlockStatement':
        entries = [error_statements(item, indent + 1) for item in node.items]
        entries = [entry for entry in entries if entry]
        return pad + 'begin\n' + '\n'.join(entries) + '\n' + pad + 'end' if entries else ''
    if kind == 'ConditionalStatement':
        yes = error_statements(node.statement, indent + 1)
        no = error_statements(node.elseClause.clause, indent + 1) if node.elseClause else ''
        if not yes and not no:
            return ''
        text = pad + 'if (' + str(node.predicate).strip() + ')\n' + (yes or pad + '  begin end')
        return text + '\n' + pad + 'else\n' + no if no else text
    if kind == 'CaseStatement':
        entries, kept = [], False
        for item in node.items:
            body = error_statements(item.clause, indent + 2)
            kept |= bool(body)
            label = 'default' if item.kind.name == 'DefaultCaseItem' else ', '.join(
                str(part).strip() for part in item.expressions if str(part).strip() != ',')
            entries.append(pad + '  ' + label + ':\n' + (body or pad + '    begin end'))
        return (pad + 'case (' + str(node.expr).strip() + ')\n' +
                '\n'.join(entries) + '\n' + pad + 'endcase') if kept else ''
    if kind in ('EmptyStatement', 'ForLoopStatement'):
        assert not re.search(r'\berror\s*<=', str(node))
        return ''
    raise ValueError((kind, str(node)[:80]))


def cone_source(reference):
    tree = SyntaxTree.fromFile(str(reference))
    module = tree.root.members[0]
    process = [item for item in module.members if 'Always' in item.kind.name][-1]
    runtime = process.statement.statement.items[0].elseClause.clause
    original = error_statements(runtime)
    source = CONTROL.read_text()
    first = source.index('  // 错误来源在本地状态译码内归并')
    last = source.index('  always_ff @(posedge clk or negedge rst_n)', first)
    candidate = source[first:last]
    ports = [('state', 6), ('load_kind', 3), ('error', 2), ('valid_taps', 9), ('soft_error', 2)]
    ports += [(name, 1) for name in (
        'start', 'config_check_done', 'config_check_error', 'load_completion_error',
        'param_bad_seen', 'read_done_q', 'read_error_q', 'pool_read_complete_saved',
        'writeback_busy', 'avg_pool', 'soft_done', 'writeback_done', 'writeback_error',
        'window_response_fault', 'p_shared_storage_enable', 'i_storage_error', 'state_failed')]
    declarations = ',\n'.join('input logic ' + (f'[{width-1}:0] ' if width > 1 else '') + name
                              for name, width in ports)
    result = ('module error_cone(\n' + declarations + ',\noutput logic [1:0] expected,actual,\n'
              'output logic equal);\n' + candidate + '\nassign actual=error_next;\n'
              'always_comb begin\n  expected=error;\n' + original + '\nend\n'
              'assign equal=expected==actual;\nendmodule\n')
    return result, ports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = PACKAGES + [CONTROL, SELECT, Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in files}
    reference = out / 'reference.sv'
    reference.write_bytes(subprocess.check_output(
        ['git', 'show', f'{REFERENCE}:rtl/npu/conv/vector_engine_control.sv'], cwd=ROOT))
    results = []
    for tile, shared in ((8, 0), (8, 1), (16, 0), (16, 1)):
        options = (f'-Gp_tile={tile} -Gp_bus_width=64 -Gp_dma_size={4*tile} -Gp_pe_count=8 '
                   f'-Gp_window_lanes=8 -Gp_shared_quant_enable={shared} '
                   f'-Gp_shared_storage_enable={shared}')
        commands = []
        for label, inputs in [('reference', [reference]), ('candidate', [CONTROL, SELECT])]:
            commands += ['read_slang --top vector_engine_control -DSYNTHESIS=1 ' + options +
                         ' ' + shlex.join(map(str, PACKAGES + inputs)),
                         'prep -top vector_engine_control -flatten', 'async2sync', 'opt -full',
                         'opt_clean -purge', f'rename vector_engine_control {label}',
                         f'design -stash {label}']
        commands += ['design -copy-from reference -as reference reference',
                     'design -copy-from candidate -as candidate candidate',
                     'equiv_make reference candidate equivalent', 'hierarchy -top equivalent',
                     'equiv_simple -seq 1', 'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
        script = out / f'tile{tile}_shared{shared}.ys'
        script.write_text('\n'.join(commands) + '\n')
        execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                 '--worker', str(script)], script.with_suffix('.log'))
        results.append({'tile': tile, 'shared_resources': shared, 'passed': True})
        print(f'tile={tile} shared={shared} PASS', flush=True)
    cone, ports = cone_source(reference)
    checker = out / 'error_cone.sv'
    checker.write_text(cone)
    sources = [PACKAGES[-1], SELECT, checker]
    script = out / 'cone.ys'
    script.write_text('read_slang --top error_cone ' + shlex.join(map(str, sources)) + '\n'
        'setattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
        'prep -top error_cone -flatten\nsat -verify -prove equal 1 -show-inputs -show-outputs\n')
    execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
            out / 'cone.log')
    width = sum(bits for _, bits in ports)
    declarations = '\n'.join('wire ' + (f'[{bits-1}:0] ' if bits > 1 else '') + name + ';'
                              for name, bits in ports)
    names = ','.join(name for name, _ in ports)
    connections = ','.join('.' + name + '(' + name + ')' for name, _ in ports)
    bench = out / 'tb.sv'
    bench.write_text(f'''module tb;
logic [{width-1}:0] inputs,saved;
{declarations}
wire[1:0] expected,actual;
wire equal;
integer checks=0;
assign {{{names}}}=inputs;
error_cone dut({connections},.expected(expected),.actual(actual),.equal(equal));
task verify;
  #1;if(actual!==expected)$fatal(1,"错误状态结果不一致 inputs=%h expected=%b actual=%b",inputs,expected,actual);
  checks++;
endtask
initial begin
  for(int sample=0;sample<50000;sample++)begin
    inputs={{$random,$random}};
    if(sample%7==0) inputs='0;
    if(sample%7==1) inputs='1;
    verify();saved=inputs;
    inputs[sample%{width}]=1'bx;verify();inputs=saved;
    inputs[(sample*13)%{width}]=1'bz;verify();
  end
  $display("ERROR_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
''')
    for synthesis in (False, True):
        label = 'synthesis' if synthesis else 'generic'
        binary = out / (label + '.vvp')
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(binary)]
        if synthesis:
            command += ['-DSYNTHESIS=1']
        execute(command + list(map(str, sources + [bench])), out / (label + '_build.log'))
        execute(['vvp', str(binary)], out / (label + '.log'))
        assert 'ERROR_FOUR_STATE_PASS checks=150000' in (out / (label + '.log')).read_text()
    assert hashes == {str(path.relative_to(ROOT)): digest(path) for path in files}
    report = {'passed': True, 'inputs_constrained': False, 'reference_commit': REFERENCE,
              'source_sha256': hashes, 'control_profiles': results,
              'complete_error_function_formal': True, 'four_state_comparisons': 300000}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('complete error function and 300000 four-state comparisons PASS')


if __name__ == '__main__':
    main()
