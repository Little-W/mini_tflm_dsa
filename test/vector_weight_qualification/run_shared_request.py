#!/usr/bin/env python3
"""验证共享存储权重写请求资格的完整状态、输出与四态行为。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/buffers/vector_shared_store.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(source):
    """移除声明中的文字注释，保持全部 RTL 表达式与时序结构。"""
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    source = source.replace('input  wire logic', 'input  logic')
    source = re.sub(r'\s+,', ',', source)
    return re.sub(r'[ \t]+\n', '\n', source)


def miter(reference, current):
    ports = re.findall(r'    (input|output)  ?logic\s*(\[[^\]]+\])?\s*(\w+)\s*(\[\d+\])?[,\n]', reference)
    assert len(ports) == 37
    header = '''module comparison #(
 parameter p_bank_bytes=8192, p_total_bytes=57344,
 parameter p_addr_width=$clog2(p_total_bytes/16),
 parameter p_bank_count_width=$clog2(p_total_bytes/p_bank_bytes+1),
 parameter p_fixed_ps_channels=1, p_specialized=1
)(
'''
    inputs = []
    declarations = []
    checks = []
    for direction, width, name, array in ports:
        if direction == 'input':
            inputs.append(f' input logic {width} {name} {array}, // 两个实现共用的任意外部输入')
        else:
            for label in ['reference', 'current']:
                declarations.append(f' wire {width} {label}_{name} {array};')
            count = int(array[1:-1]) if array else 1
            for index in range(count):
                item = f'[{index}]' if array else ''
                checks.append(f'(reference_{name}{item} == current_{name}{item})')
    header += '\n'.join(inputs) + '\n output logic equivalent // 完整状态与输出相同\n);\n'
    header += '\n'.join(declarations) + '\n'
    for label in ['reference', 'current']:
        header += f'''{label} #(.p_bank_bytes(p_bank_bytes), .p_total_bytes(p_total_bytes),
 .p_fixed_ps_channels(p_fixed_ps_channels)'''
        if label == 'current':
            header += ', .p_weight_nonempty_writes(p_specialized)'
        header += f') u_{label}(\n' + ',\n'.join(
            f' .{name}({name if direction == "input" else label+"_"+name})'
            for direction, width, name, array in ports) + '\n);\n'
    for name in ['configured', 'ia_word_limit', 'weight_return_vld', 'ps_return_vld']:
        checks.append(f'(u_reference.{name} == u_current.{name})')
    header += 'assign equivalent = ' + ' &&\n'.join(checks) + ';\n'
    header += '''always_comb begin
 if (p_specialized) assume (!i_weight_write_en || (|i_weight_write_mask));
end
endmodule
'''
    return (reference.replace('module vector_shared_store #(', 'module reference #(', 1) + '\n' +
            current.replace('module vector_shared_store #(', 'module current #(', 1) + '\n' + header)


def execute(command, log, timeout=180):
    with log.open('w') as stream:
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True,
                       stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='aa246aef')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve()
    original = subprocess.check_output(['git', 'show', args.reference+':'+str(SOURCE)], cwd=ROOT, text=True)
    reference = normalize(original)
    current = normalize((source_root/SOURCE).read_text())
    model = out/'comparison.sv'; model.write_text(miter(reference, current))
    worker = [sys.executable, ROOT/'scripts/fpga/open_fpga_synth.py', '--worker']
    formal = []
    for specialized in [0, 1]:
        for size, banks, fixed in [(2048, 6, 0), (2048, 8, 1), (8192, 7, 1), (4096, 9, 0)]:
            label = f'b{size}_n{banks}_f{fixed}_q{specialized}'
            script, log = out/(label+'.ys'), out/(label+'.log')
            script.write_text(shlex.join(['read_slang', '--top', 'comparison', f'-Gp_bank_bytes={size}',
                f'-Gp_total_bytes={size*banks}', f'-Gp_fixed_ps_channels={fixed}',
                f'-Gp_specialized={specialized}', str(model)]) +
                '\nprep -top comparison -flatten\nasync2sync\nopt_clean\n'
                'sat -verify -tempinduct -seq 2 -set-at 1 rst_n 0 -set-assumes -prove equivalent 1\n')
            execute(worker+[script], log)
            text = log.read_text(); assert 'Induction step proven: SUCCESS!' in text
            formal.append({'passed': True, 'bank_bytes': size, 'banks': banks,
                           'fixed_ps_channels': fixed, 'nonempty_writes': specialized,
                           'induction_depth': max(map(int, re.findall(r'\[induction step (\d+)\]', text))),
                           'log_sha256': digest(log)})
            print('VECTOR_SHARED_REQUEST_PASS', label, flush=True)
    helper = ROOT/'test/vector_storage_qualification/run.py'
    four_state_source = runpy.run_path(str(helper))['four_state_source']
    four_state = []
    for specialized in [0, 1]:
        candidate = current
        if specialized:
            candidate = candidate.replace("parameter bit p_weight_nonempty_writes = 1'b0",
                                          "parameter bit p_weight_nonempty_writes = 1'b1")
        bench = four_state_source(reference, candidate)
        if specialized:
            # 仅有效写请求要求掩码包含已知的一；未知有效位仍按通用四态逻辑处理。
            marker = '\n #1;'
            assert bench.count(marker) == 1
            bench = bench.replace(marker, "\n if(i_weight_write_en === 1'b1)i_weight_write_mask[0]=1'b1;"+marker)
        model4 = out/f'four_state_{specialized}.sv'; model4.write_text(bench)
        binary, log = out/f'four_state_{specialized}.vvp', out/f'four_state_{specialized}.log'
        execute(['iverilog', '-g2012', '-s', 'tb', '-o', binary, model4],
                out/f'four_state_{specialized}_compile.log')
        execute(['vvp', binary], log, timeout=600)
        match = re.search(r'VECTOR_STORAGE_FOUR_STATE_PASS comparisons=(\d+)', log.read_text())
        assert match
        four_state.append({'nonempty_writes': specialized, 'passed': True,
                           'profiles': 12, 'cycles_per_profile': 4096,
                           'comparisons': int(match[1]), 'log_sha256': digest(log)})
    report = {'passed': True, 'reference_revision': args.reference,
              'source_sha256': digest(source_root/SOURCE),
              'reference_sha256': hashlib.sha256(original.encode()).hexdigest(),
              'generic_inputs': '首个采样周期复位，后续输入和复位自由',
              'specialized_inputs': '有效权重写请求至少包含一个已置位的字节掩码；其他输入自由',
              'formal_profiles': formal, 'four_state_profiles': four_state,
              'test_sha256': digest(Path(__file__)), 'helper_sha256': digest(helper)}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print('VECTOR_SHARED_REQUEST_ALL_PASS', flush=True)


if __name__ == '__main__':
    main()
