#!/usr/bin/env python3
"""验证完整流式状态与请求选择，覆盖任意输入和四态控制。"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--reference', default='32379597')
    parser.add_argument('--modes', nargs='+', choices=('generic', 'fpga'), default=['generic', 'fpga'])
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    actual = (args.candidate or root/'rtl/npu/conv/conv_im2col_stream_control.sv').resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = subprocess.check_output(['git', 'show', args.reference+':rtl/npu/conv/conv_im2col_stream_control.sv'], cwd=ROOT, text=True)
    models = []
    for label, source in [('reference', reference), ('current', actual.read_text())]:
        path = out/(label+'.sv')
        path.write_text(source.replace('module conv_im2col_stream_control', 'module '+label+'_stream_control').replace('unique case', 'case'))
        models.append(path)
    resolve = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))['with_dependencies']
    sources = resolve(models, root)
    inputs, outputs, declarations = [], [], []
    ports = reference[reference.index('module conv_im2col_stream_control ('):reference.index('\n);')]
    for line in ports.splitlines()[1:]:
        clean = line.split('//')[0].strip().rstrip(',')
        found = re.match(r'(input|output)\s+(.*)\s+([io]_\w+)$', clean)
        if found is None:
            continue
        direction, kind, name = found.groups()
        if direction == 'input':
            inputs.append((kind, name))
        else:
            outputs.append((kind, name))
            for label in ('reference', 'current'):
                declarations.append(kind+' '+label+'_'+name+';')
    count = len(inputs)
    assert count == 17
    connections = []
    for label in ('reference', 'current'):
        values = [f'.{name}({name})' for _, name in inputs]+[f'.{name}({label}_{name})' for _, name in outputs]
        connections.append(label+'_stream_control u_'+label+'('+','.join(values)+');')
    left = '{'+','.join('reference_'+name for _, name in outputs)+'}'
    right = '{'+','.join('current_'+name for _, name in outputs)+'}'
    generated = out/'proof.sv'
    generated.write_text('module proof(\n'+',\n'.join('input '+kind+' '+name for kind, name in inputs)+',\noutput logic equivalent);\n'+
        '\n'.join(declarations+connections)+f'\nassign equivalent=({left}=={right});\nendmodule\n')
    tb = out/'tb.sv'
    lines = ['module tb;', f'logic [{count-1}:0] stimulus, known;', 'integer seed=32\'h73280145,checks=0;']
    lines += [f'wire {name}=stimulus[{i}];' for i, (_, name) in enumerate(inputs)]
    lines += declarations+connections
    lines += ['task check;', 'begin #1;checks++;', f'if({left}!=={right})$fatal(1,"stream input=%h expected=%h actual=%h",stimulus,{left},{right});', 'end endtask', 'initial begin',
        f'for(integer sample=0;sample<{1<<count};sample++)begin stimulus=sample;check();end',
        'for(integer sample=0;sample<256;sample++)begin', 'known=$random(seed);',
        f'for(integer bit_index=0;bit_index<{count};bit_index++)begin',
        "stimulus=known;stimulus[bit_index]=1'bx;check();", "stimulus=known;stimulus[bit_index]=1'bz;check();", 'end end',
        'for(integer sample=0;sample<20000;sample++)begin', f'for(integer bit_index=0;bit_index<{count};bit_index++)begin',
        "case($unsigned($random(seed))%8) 2:stimulus[bit_index]=1'bx;3:stimulus[bit_index]=1'bz;default:stimulus[bit_index]=$random(seed);endcase", 'end check();end',
        "stimulus='x;check();stimulus='z;check();", '$display("STREAM_CONTROL_PASS checks=%0d",checks);$finish;end endmodule']
    tb.write_text('\n'.join(lines)+'\n')
    hashes = {str(path): digest(path) for path in [actual, *sources]}
    records = []

    def execute(command, log):
        with log.open('w') as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=300, check=True)

    for mode in args.modes:
        synthesis = mode == 'fpga'
        name = 'synthesis' if synthesis else 'generic'
        definitions = ['-DSYNTHESIS=1', '-DXILINX_FPGA=1'] if synthesis else []
        script, formal = out/(name+'.ys'), out/(name+'_formal.log')
        script.write_text('read_slang --top proof '+shlex.join((definitions if synthesis else ['-USYNTHESIS', '-UXILINX_FPGA'])+list(map(str, sources+[generated])))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\nprep -top proof -flatten\nopt -full\nsat -verify -prove equivalent 1\n')
        execute([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], formal)
        binary = out/(name+'.vvp')
        execute(['iverilog', '-g2012', '-s', 'tb', *definitions, '-o', str(binary), *map(str, sources), str(tb)], out/(name+'_compile.log'))
        simulation = out/(name+'_four.log')
        execute(['vvp', str(binary)], simulation)
        match = re.search(r'STREAM_CONTROL_PASS checks=(\d+)', simulation.read_text())
        if match is None:
            raise RuntimeError(str(simulation))
        binary.unlink()
        records.append(dict(synthesis=synthesis, slang_definitions=definitions if synthesis else ['-USYNTHESIS', '-UXILINX_FPGA'], passed=True, formal_log_sha256=digest(formal), four_state_checks=int(match[1]), four_state_log_sha256=digest(simulation)))
        print(name, 'PASS', match[1], flush=True)
    assert all(digest(Path(path)) == value for path, value in hashes.items())
    report = dict(passed=True, reference=args.reference, source_sha256=hashes, input_assumptions=[], all_public_outputs_compared=True, profiles=records, test_sha256=digest(Path(__file__)))
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
