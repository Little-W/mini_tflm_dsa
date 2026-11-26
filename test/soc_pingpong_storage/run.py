#!/usr/bin/env python3
"""验证两项 AXI 缓冲的存储实现、复位可见值与四态握手。"""
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
SOURCE = Path('rtl/soc/soc_axi_pingpong_chan.sv')
WIDTHS = (1, 2, 23, 24, 34, 35, 36, 54, 64, 67, 73, 128)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expose(text, label):
    text = text.replace('module soc_axi_pingpong_chan #(', f'module {label} #(', 1)
    text, count = re.subn(
        r'(output logic \[WIDTH-1:0\] m_data[^\n]*)\n\);',
        r'\1,\n    output wire [2*WIDTH+3:0] formal_state,\n    output wire formal_legal\n);',
        text, count=1)
    if count != 1:
        raise RuntimeError('通道输出声明未找到')
    return text.replace('endmodule', '''    assign formal_state = {data0_q, data1_q, rd_sel_q, wr_sel_q, occupied_q, full_q};
    assign formal_legal = !full_q || occupied_q;
endmodule''', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='ce47de48')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=100000)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current_path = args.source_root.resolve() / SOURCE
    current = current_path.read_text()
    reference = subprocess.check_output(
        ['git', 'show', f'{args.reference}:{SOURCE}'], cwd=ROOT, text=True)
    paths = []
    for label, text in [('reference', reference), ('current', current)]:
        path = out / f'{label}.sv'
        path.write_text(expose(text, label))
        paths.append(path)
    miter = out / 'miter.sv'
    miter.write_text('''module miter #(parameter integer WIDTH=1)(
    input wire clk, rst_n, s_valid, m_ready,
    input wire [WIDTH-1:0] s_data, output wire correct
);
    wire r_ready, r_valid, c_ready, c_valid, r_legal, c_legal;
    wire [WIDTH-1:0] r_data, c_data;
    wire [2*WIDTH+3:0] r_state, c_state;
    reference #(.WIDTH(WIDTH)) r (
        .clk, .rst_n, .s_valid, .m_ready, .s_data, .s_ready(r_ready),
        .m_valid(r_valid), .m_data(r_data), .formal_state(r_state), .formal_legal(r_legal));
    current #(.WIDTH(WIDTH)) c (
        .clk, .rst_n, .s_valid, .m_ready, .s_data, .s_ready(c_ready),
        .m_valid(c_valid), .m_data(c_data), .formal_state(c_state), .formal_legal(c_legal));
    assign correct = {r_ready, r_valid, r_data, r_state} ==
                     {c_ready, c_valid, c_data, c_state} && r_legal && c_legal;
endmodule
''')
    report = {
        'reference': args.reference, 'source_sha256': digest(current_path),
        'reference_sha256': hashlib.sha256(reference.encode()).hexdigest(),
        'initial_reset_cycle': 1, 'functional_inputs_constrained': False,
        'all_public_outputs_compared': True, 'invalid_data_compared': True,
        'logical_storage_and_positions_compared': True,
        'formal': [], 'four_state': [], 'passed': False}
    for mode, defines in [('generic', []), ('fpga_synthesis', ['SYNTHESIS=1', 'XILINX_FPGA=1'])]:
        flags = ' '.join('-D' + define for define in defines)
        for width in WIDTHS:
            name = f'{mode}_width{width}'
            script, log = out / (name + '.ys'), out / (name + '.log')
            script.write_text(
                f'read_slang {flags} --top miter -GWIDTH={width} ' +
                shlex.join(str(p) for p in [*paths, miter]) + '\n'
                'prep -top miter -flatten\nmemory_map\nopt\n'
                'sat -seq 2 -prove-skip 1 -prove correct 1 -verify -set-def-inputs '
                '-set-init-def -set-at 1 rst_n 0\n'
                'sat -seq 1 -tempinduct-inductonly -tempinduct-def -maxsteps 4 '
                '-prove correct 1 -verify -set-def-inputs -set-init-def\n')
            with log.open('w') as stream:
                subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                '--worker', str(script)], stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=180)
            text = log.read_text()
            if 'Induction step proven: SUCCESS!' not in text:
                raise RuntimeError('存储状态归纳证明未完成')
            report['formal'].append({'mode': mode, 'width': width, 'passed': True,
                                     'compared_bits': 3 * width + 6, 'log_sha256': digest(log)})
            print(name, 'PASS', flush=True)
    original_bench = (ROOT / 'test/axi_occupancy/tb_four_state.sv').read_text()
    original_bench = original_bench.replace('[72:0]', '[127:0]').replace('[0:8]', '[0:11]')
    first = original_bench.index('    occupancy_compare #(.WIDTH(1))')
    last = original_bench.index('\n\n    initial begin', first)
    instances = '\n'.join(f'    occupancy_compare #(.WIDTH({width})) w{width} (.*,.checks(checks[{i}]));'
                          for i, width in enumerate(WIDTHS))
    original_bench = original_bench[:first] + instances + original_bench[last:]
    original_bench = original_bench.replace('i < 9', 'i < 12').replace('widths=9', 'widths=12')
    original_bench = original_bench.replace('(2*cycles+1)*9', '(2*cycles+1)*12')
    original_bench = original_bench.replace('{$urandom, $urandom, $urandom}',
                                            '{$urandom, $urandom, $urandom, $urandom}')
    original_bench = original_bench.replace("data[72:64] = 'x", "data[127:64] = 'x")
    bench = out / 'tb_four_state.sv'
    bench.write_text(original_bench)
    for mode, defines in [('generic', []), ('fpga', ['XILINX_FPGA=1']),
                          ('fpga_synthesis', ['SYNTHESIS=1', 'XILINX_FPGA=1'])]:
        binary, compile_log = out / (mode + '.vvp'), out / (mode + '_compile.log')
        with compile_log.open('w') as log:
            subprocess.run(['iverilog', '-g2012', *('-D' + d for d in defines),
                            '-s', 'tb_axi_occupancy', '-o', str(binary),
                            str(bench), *map(str, paths)], stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        result = subprocess.run(['vvp', str(binary), f'+cycles={args.cycles}'],
                                capture_output=True, text=True, check=True, timeout=240)
        log = out / (mode + '_four_state.log')
        log.write_text(result.stdout + result.stderr)
        checks = (2 * args.cycles + 1) * len(WIDTHS)
        expected = f'AXI_OCCUPANCY_PASS cycles={args.cycles} widths=12 output_checks={checks}'
        if expected not in result.stdout:
            raise RuntimeError('四态输出与状态比较未完成')
        report['four_state'].append({'mode': mode, 'cycles': args.cycles,
            'comparisons': checks, 'unknown_controls': True, 'unknown_payload': True,
            'passed': True, 'log_sha256': digest(log)})
        print(mode, 'FOUR_STATE_PASS', checks, flush=True)
    if current != current_path.read_text():
        raise RuntimeError('验证期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
