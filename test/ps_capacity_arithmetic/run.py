#!/usr/bin/env python3
"""检查部分和容量完整加法的全部输入与四态事件语义。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/ps_compact/ps_frame_store.sv')
PROFILES = [(1, 1, 1), (1, 2, 2), (4, 4, 3), (10, 8, 3),
            (14, 10, 4), (12, 10, 4), (16, 12, 4), (8, 12, 5),
            (31, 10, 4), (32, 10, 4), (14, 30, 4), (34, 12, 4)]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract(text, name):
    start = text.index('module ps_frame_store_capacity #(')
    end = text.index('endmodule', start) + len('endmodule')
    return text[start:end].replace('module ps_frame_store_capacity', 'module ' + name, 1)


def execute(command, log):
    with log.open('w') as stream:
        subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
    return log.read_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference', default='cedf4ed33661a53c8194eca1d484cdc2279d7549')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = args.source_root / SOURCE
    current = source.read_text()
    reference = subprocess.check_output(['git', 'show', f'{args.reference}:{SOURCE}'],
                                        cwd=ROOT, text=True)
    prefix = ROOT / 'rtl/common/parallel_prefix_add.sv'
    arithmetic = out / 'arithmetic.sv'
    arithmetic.write_text(extract(current, 'ps_frame_store_capacity') + '\n' +
                          extract(reference, 'reference_capacity') + '\n')
    harness = ROOT / 'test/ps_raw_store/capacity.sv'
    report = {'passed': False, 'source_sha256': digest(source),
              'reference_commit': args.reference,
              'reference_source_sha256': hashlib.sha256(reference.encode()).hexdigest(),
              'test_source_sha256': digest(Path(__file__)), 'inputs_constrained': False,
              'formal': [], 'four_state': []}
    for mode in ('fpga', 'asic'):
        for initial, words, banks in PROFILES:
            label = f'{mode}_i{initial}_w{words}_b{banks}'
            script = out / (label + '.ys')
            log = out / (label + '.log')
            define = 'XILINX_FPGA' if mode == 'fpga' else 'ASIC_SYNTHESIS'
            script.write_text('read_slang --top ps_frame_capacity_formal -D SYNTHESIS=1 ' +
                f'-D {define}=1 -GINITIAL_W={initial} -GWORDS_W={words} -GBANKS_W={banks} ' +
                shlex.join(map(str, [prefix, arithmetic, harness])) + '\n' +
                'prep -top ps_frame_capacity_formal -flatten\ncheck -assert\n' +
                'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
            text = execute([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                            '--worker', str(script)], log)
            if 'SAT proof finished - no model found: SUCCESS!' not in text:
                raise RuntimeError('容量表达式证明未完成：' + label)
            record = {'mode': mode, 'initial_row_width': initial, 'bank_words_width': words,
                      'bank_count_width': banks, 'passed': True, 'log_sha256': digest(log)}
            report['formal'].append(record)
            print(json.dumps(record), flush=True)
    for initial, words, banks in ((1, 1, 1), (14, 10, 4), (32, 10, 4), (34, 12, 4)):
        width = initial + words + banks + 64
        label = f'four_i{initial}_w{words}_b{banks}'
        bench = out / (label + '.sv')
        bench.write_text(f'''module tb;
    reg [{width-1}:0] values;
    wire [{initial-1}:0] initial_row = values[0+:{initial}];
    wire [31:0] frame_rows = values[{initial}+:32];
    wire [31:0] reserve_rows = values[{initial+32}+:32];
    wire [{words-1}:0] bank_words = values[{initial+64}+:{words}];
    wire [{banks-1}:0] bank_count = values[{initial+64+words}+:{banks}];
    wire actual, expected;
    integer sample, bit_index, choice;
    reg [31:0] random_state = 32'h631d9a27;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value = value ^ (value << 13);
            next_value = next_value ^ (next_value >> 17);
            step = next_value ^ (next_value << 5);
        end
    endfunction
    ps_frame_store_capacity #(.p_initial_row_width({initial}), .p_bank_words_width({words}),
        .p_bank_count_width({banks})) dut(initial_row, frame_rows, reserve_rows,
        bank_words, bank_count, actual);
    reference_capacity #(.p_initial_row_width({initial}), .p_bank_words_width({words}),
        .p_bank_count_width({banks})) reference_dut(initial_row, frame_rows, reserve_rows,
        bank_words, bank_count, expected);
    initial begin
        for (sample=0; sample<32768; sample=sample+1) begin
            for (bit_index=0; bit_index<{width}; bit_index=bit_index+1) begin
                random_state=step(random_state);
                choice=sample<8192 ? int'(random_state[0]) : int'(random_state[1:0]);
                case(choice)
                    0: values[bit_index]=1'b0;
                    1: values[bit_index]=1'b1;
                    2: values[bit_index]=1'bx;
                    3: values[bit_index]=1'bz;
                endcase
            end
            #1;
            if (actual !== expected) $fatal(1,"Capacity differs at sample %0d",sample);
        end
        $display("CAPACITY_FOUR_STATE_PASS samples=32768");
        $finish;
    end
endmodule
''')
        binary = out / (label + '.vvp')
        execute(['iverilog', '-g2012', '-s', 'tb', '-o', str(binary), str(prefix),
                 str(arithmetic), str(bench)], out / (label + '_build.log'))
        log = out / (label + '_run.log')
        text = execute(['vvp', str(binary)], log)
        if 'CAPACITY_FOUR_STATE_PASS' not in text:
            raise RuntimeError('容量四态比较未完成')
        report['four_state'].append({'initial_row_width': initial, 'bank_words_width': words,
                                    'bank_count_width': banks, 'comparisons': 32768,
                                    'passed': True, 'log_sha256': digest(log)})
    if current != source.read_text():
        raise RuntimeError('检查期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'formal_profiles': len(report['formal']),
                      'four_state_comparisons': 131072}))


if __name__ == '__main__':
    main()
