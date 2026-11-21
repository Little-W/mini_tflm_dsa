#!/usr/bin/env python3
"""比较实际激活裁剪条件在完整四态输入下的事件结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path('rtl/npu/writeback/vec_requant.sv')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    modules = out / 'comparison.sv'
    pieces = []
    for name, text in [('current', current), ('reference', reference)]:
        module = re.search(r'module requant_activation_compare\b.*?endmodule', text, re.S)[0]
        pieces.append(module.replace('requant_activation_compare', name + '_comparison'))
    modules.write_text('\n'.join(pieces) + '\n')
    bench = out / 'tb.sv'
    bench.write_text('''module tb;
    reg [99:0] values;
    wire [1:0] actual, expected;
    integer sample, bit_index, choice;
    reg [31:0] random_state=32'h2b73a195;
    function automatic [31:0] step(input [31:0] value);
        reg [31:0] next_value;
        begin
            next_value=value^(value<<13);
            next_value=next_value^(next_value>>17);
            step=next_value^(next_value<<5);
        end
    endfunction
    current_comparison current_dut(values[35:0],values[67:36],values[99:68],actual[0],actual[1]);
    reference_comparison reference_dut(values[35:0],values[67:36],values[99:68],expected[0],expected[1]);
    initial begin
        for(sample=0;sample<65536;sample=sample+1) begin
            for(bit_index=0;bit_index<100;bit_index=bit_index+1) begin
                random_state=step(random_state);
                choice=sample<16384 ? int'(random_state[0]) : int'(random_state[1:0]);
                case(choice)
                    0: values[bit_index]=1'b0;
                    1: values[bit_index]=1'b1;
                    2: values[bit_index]=1'bx;
                    3: values[bit_index]=1'bz;
                endcase
            end
            #1;
            if(actual !== expected) $fatal(1,"Activation flags differ at sample %0d",sample);
        end
        $display("ACTIVATION_FOUR_STATE_PASS samples=65536");
        $finish;
    end
endmodule
''')
    report = {'passed': False, 'source_sha256': digest(source),
              'test_source_sha256': digest(Path(__file__)), 'reference_commit': args.reference,
              'strict_four_state': True, 'profiles': []}
    for label, definitions in [('generic', []), ('fpga', ['-DXILINX_FPGA=1']),
                               ('asic', ['-DASIC_SYNTHESIS=1'])]:
        binary = out / (label + '.vvp')
        with (out / (label + '_build.log')).open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'tb', *definitions, '-o', str(binary),
                            str(modules), str(bench)], stdout=stream, stderr=subprocess.STDOUT,
                           check=True)
        result = subprocess.run(['vvp', str(binary)], capture_output=True, text=True,
                                check=True, timeout=180)
        log = out / (label + '_run.log')
        log.write_text(result.stdout + result.stderr)
        if 'ACTIVATION_FOUR_STATE_PASS' not in result.stdout:
            raise RuntimeError('激活条件四态检查未完成')
        report['profiles'].append({'mode': label, 'passed': True, 'samples': 65536,
                                   'compared_flags': 2, 'log_sha256': digest(log)})
    if current != source.read_text():
        raise RuntimeError('检查期间源码发生变化')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'samples': 196608, 'compared_flags': 2}))


if __name__ == '__main__':
    main()
