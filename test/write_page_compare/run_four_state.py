#!/usr/bin/env python3
"""逐周期比较写入分页模块在二值、未知值和高阻值输入下的输出。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/dma/axi_write_page_guard.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    current = (args.source_root / SOURCE).read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    paths = []
    for label, text in [('current', current), ('reference', reference)]:
        path = out / (label + '.sv')
        path.write_text(text.replace('module axi_write_page_guard #(', f'module guard_{label} #(', 1))
        paths.append(path)
    header = current[:current.index(');')]
    ports = []
    for match in re.finditer(r'(input|output)\s+logic\s*(\[[^]]*\])?\s*'
                            r'([A-Za-z_]\w*(?:\s*,\s*(?!input\b|output\b)[A-Za-z_]\w*)*)', header):
        for name in re.sub(r'\s+', '', match[3]).split(','):
            ports.append((match[1], match[2] or '', name))
    if len(ports) != 31:
        raise RuntimeError('写入分页端口提取结果与实际接口不同')
    declarations, current_ports, reference_ports = [], [], []
    inputs, outputs_current, outputs_reference = [], [], []
    for direction, width, name in ports:
        if direction == 'input':
            declarations.append(f'    reg {width} {name};')
            current_ports.append(f'.{name}({name})')
            reference_ports.append(f'.{name}({name})')
            if name not in ('clk', 'rst_n'):
                inputs.append(name)
        else:
            declarations.append(f'    wire {width} current_{name}, reference_{name};')
            current_ports.append(f'.{name}(current_{name})')
            reference_ports.append(f'.{name}(reference_{name})')
            outputs_current.append('current_' + name)
            outputs_reference.append('reference_' + name)
    input_concat = '{' + ','.join(inputs) + '}'
    current_concat = '{' + ','.join(outputs_current) + '}'
    reference_concat = '{' + ','.join(outputs_reference) + '}'
    bench = out / 'four_state.sv'
    bench.write_text('module four_state #(parameter ADDR_W=32, DATA_W=64, WRITE_OUTSTANDING=4);\n' +
        '\n'.join(declarations) + '\n' +
        '    guard_current #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) current_dut(' +
        ','.join(current_ports) + ');\n' +
        '    guard_reference #(.ADDR_W(ADDR_W), .DATA_W(DATA_W), .WRITE_OUTSTANDING(WRITE_OUTSTANDING)) reference_dut(' +
        ','.join(reference_ports) + ');\n' + f'''
    localparam INPUT_BITS = $bits({input_concat});
    reg [INPUT_BITS-1:0] samples;
    reg [31:0] random_state = 32'h924fad31;
    integer cycle, bit_index, choice;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value = value ^ (value << 13);
            next_value = next_value ^ (next_value >> 17);
            step = next_value ^ (next_value << 5);
        end
    endfunction
    task automatic compare_outputs;
        if ({current_concat} !== {reference_concat})
            $fatal(1, "Write page output mismatch at cycle %0d", cycle);
    endtask
    initial begin
        clk = 0; rst_n = 0; {input_concat} = '0;
        #1; clk = 1; #1; clk = 0;
        for (cycle = 0; cycle < 16384; cycle = cycle + 1) begin
            rst_n = cycle % 37 != 0;
            for (bit_index = 0; bit_index < INPUT_BITS; bit_index = bit_index + 1) begin
                random_state = step(random_state);
                choice = cycle < 8192 ? int'(random_state[0]) : int'(random_state[1:0]);
                case (choice)
                    0: samples[bit_index] = 1'b0;
                    1: samples[bit_index] = 1'b1;
                    2: samples[bit_index] = 1'bx;
                    3: samples[bit_index] = 1'bz;
                endcase
            end
            {input_concat} = samples;
            #1; compare_outputs(); clk = 1;
            #1; compare_outputs(); clk = 0;
        end
        $display("WRITE_PAGE_FOUR_STATE_PASS cycles=16384 comparisons=32768");
        $finish;
    end
endmodule
''')
    report = {'passed': False, 'reference_commit': args.reference,
              'source_sha256': digest(args.source_root / SOURCE),
              'test_source_sha256': digest(Path(__file__)), 'profiles': []}
    for address_width, data_width in [(32, 32), (32, 64), (12, 8), (40, 128)]:
        name = f'address{address_width}_data{data_width}'
        binary = out / (name + '.vvp')
        run(['iverilog', '-g2012', '-s', 'four_state', f'-Pfour_state.ADDR_W={address_width}',
             f'-Pfour_state.DATA_W={data_width}', '-o', str(binary),
             *(str(p) for p in paths), str(bench)], out / (name + '_build.log'))
        log = out / (name + '.log')
        run(['vvp', str(binary)], log)
        if 'WRITE_PAGE_FOUR_STATE_PASS' not in log.read_text():
            raise RuntimeError('写入分页四态比较未完成')
        report['profiles'].append({'address_width': address_width, 'data_width': data_width,
                                  'passed': True, 'cycles': 16384, 'comparisons': 32768,
                                  'log_sha256': digest(log)})
    report['passed'] = True
    report['comparisons'] = sum(row['comparisons'] for row in report['profiles'])
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
