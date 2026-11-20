#!/usr/bin/env python3
"""证明下一次访问预测器的全部公开输出和对应状态逐周期等价。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'test'))
from rtl_reference import read_rtl_source

SOURCES = ('rtl/npu/conv/conv_im2col_pkg.sv',
           'rtl/npu/dma/cache/conv_next_use_predictor.sv',
           'rtl/common/onehot_check.sv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    texts = {'reference': read_rtl_source(args.reference + ':' + SOURCES[1], cwd=ROOT, text=True),
             'current': (ROOT / SOURCES[1]).read_text()}
    begin = '  // 高十八位的两种借位结果并行计算，低十六位只选择相应结果。'
    bodies = {label: text[text.index(begin):text.index('  always_comb begin', text.index(begin))]
              for label, text in texts.items()}
    if texts['current'].replace(bodies['current'], bodies['reference'], 1) != texts['reference']:
        raise ValueError('坐标减法以外存在修改，需要扩展自由输入证明范围')
    units = []
    for label, body in bodies.items():
        values = ['coordinate_difference']
        for axis in range(2):
            values += [f'g_coordinate_difference[{axis}].{signal}' for signal in
                       ('low_difference', 'high_without_borrow', 'high_with_borrow')]
        units.append(f'''module arithmetic_{label}(input logic [129:0] i_value,
    output logic [173:0] o_value);
  logic [32:0] y_pad_q, x_pad_q;
  logic [31:0] mul_y_s0, mul_x_s0;
  logic signed [33:0] ny_s0, nx_s0;
  logic [1:0][32:0] coordinate_pad;
  logic [1:0][31:0] coordinate_product;
  logic [1:0][33:0] coordinate_difference;
  assign {{y_pad_q, x_pad_q, mul_y_s0, mul_x_s0}} = i_value;
''' + body + '  assign o_value = {' + ', '.join(values) + '};\nendmodule\n')
    proof = out / 'arithmetic.sv'
    proof.write_text(''.join(units) + '''module arithmetic_proof(input logic [129:0] i_value,
    output logic o_equal);
  logic [173:0] reference_value, current_value;
  arithmetic_reference u_reference(.i_value(i_value), .o_value(reference_value));
  arithmetic_current u_current(.i_value(i_value), .o_value(current_value));
  assign o_equal = reference_value == current_value;
endmodule
''')
    arithmetic_script, arithmetic_log = out / 'arithmetic.ys', out / 'arithmetic.log'
    arithmetic_script.write_text('read_slang --top arithmetic_proof ' + shlex.quote(str(proof)) +
        '\nprep -top arithmetic_proof -flatten\nsat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
    with arithmetic_log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(arithmetic_script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            check=True)
    if 'SAT proof finished - no model found: SUCCESS!' not in arithmetic_log.read_text():
        raise RuntimeError('完整坐标运算的自由输入证明未完成')
    hashes, commands = {}, []
    for label in ('reference', 'current'):
        paths = []
        hashes[label] = {}
        for name in SOURCES:
            content = read_rtl_source(args.reference + ':' + name, cwd=ROOT) \
                if label == 'reference' else (ROOT / name).read_bytes()
            target = out / label / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            hashes[label][name] = hashlib.sha256(content).hexdigest()
            paths.append(target)
        commands += ['read_slang --top conv_next_use_predictor -D SYNTHESIS=1 '
            '-D XILINX_FPGA=1 -D YOSYS=1 -D VERIFIC=1 ' +
            ' '.join(shlex.quote(str(path)) for path in paths),
            'prep -top conv_next_use_predictor -flatten', 'memory_map',
            'async2sync', 'opt_clean', 'cd conv_next_use_predictor']
        # 两种高位结果共同参与前面的自由输入证明；完整模块比较时展开其共同算术输入。
        for axis in range(2):
            commands.append(f'rename g_coordinate_difference[{axis}].high_without_borrow '
                            f'{label}_high_without_borrow_{axis}')
        commands += ['cd ..', 'rename conv_next_use_predictor ' + label,
            'design -stash ' + label]
    commands += ['design -copy-from reference reference',
        'design -copy-from current current', 'equiv_make reference current equivalent',
        'hierarchy -top equivalent', 'opt_merge', 'equiv_simple -short -seq 1',
        'opt_clean', 'equiv_induct -seq 2', 'equiv_status -assert']
    script, log = out / 'formal.ys', out / 'formal.log'
    script.write_text('\n'.join(commands) + '\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
            check=True)
    text = log.read_text()
    match = re.search(r'Of those cells (\d+) are proven and (\d+) are unproven', text)
    passed = 'Equivalence successfully proven' in text and match is not None and int(match[2]) == 0
    if not passed:
        raise RuntimeError('预测器等价证明未完成')
    report = {'passed': passed, 'reference_commit': subprocess.check_output(
        ['git', 'rev-parse', args.reference], cwd=ROOT, text=True).strip(),
        'inputs_constrained': False, 'fpga': True, 'equivalent_bits': int(match[1]),
        'arithmetic_free_input_bits': 130, 'arithmetic_observed_bits': 174,
        'arithmetic_log_sha256': hashlib.sha256(arithmetic_log.read_bytes()).hexdigest(),
        'source_sha256': hashes, 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    for name, expected in hashes['current'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('验证期间源码发生变化: ' + name)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
