#!/usr/bin/env python3
"""证明无符号比较器在全部输入下的大小关系，并检查四态输入传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WIDTHS = (1, 8, 16, 17, 24, 29, 32, 33, 47, 48, 64)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        from pyosys import libyosys
        libyosys.run_pass('script ' + shlex.quote(str(args.worker)))
        return

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/common/unsigned_compare.sv'
    formal = out / 'formal.sv'
    formal.write_text('''module formal_compare #(parameter p_width=32)(
    input [p_width-1:0] i_a, i_b,
    output o_equal
);
    wire less_result, equal_result;
    unsigned_compare #(.p_width(p_width)) u_compare (
        .i_a(i_a), .i_b(i_b), .o_less(less_result), .o_equal(equal_result)
    );
    assign o_equal = (less_result == (i_a < i_b)) &&
                     (equal_result == (i_a == i_b));
endmodule
''')
    summary = {'passed': False, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'inputs_constrained': False, 'runs': []}
    for width in WIDTHS:
        script = out / f'w{width}.ys'
        log = out / f'w{width}.log'
        script.write_text('read_verilog -sv ' + shlex.join([str(source), str(formal)]) + '\n' +
                          f'chparam -set p_width {width} formal_compare\n' +
                          'prep -top formal_compare -flatten\ncheck -assert\n' +
                          'sat -verify -prove o_equal 1 -show-inputs -show-outputs\n')
        with log.open('w') as stream:
            result = subprocess.run([sys.executable, __file__, '--out', str(out),
                                     '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT)
        passed = result.returncode == 0 and 'SAT proof finished - no model found: SUCCESS' in log.read_text()
        summary['runs'].append({'width': width, 'passed': passed})
        if not passed:
            raise RuntimeError(f'无符号比较证明未通过：{log}')

    # 输入中逐位插入未知值和高阻态，再与语言规定的关系运算符比较。
    testbench = out / 'tb_four_state.sv'
    testbench.write_text('''module tb_four_state;
    parameter p_width=32;
    reg [p_width-1:0] i_a, i_b;
    wire less_result, equal_result;
    integer count=0;
    reg [31:0] random_state=32'h2963a71b;
    unsigned_compare #(.p_width(p_width)) u_compare (
        .i_a(i_a), .i_b(i_b), .o_less(less_result), .o_equal(equal_result)
    );
    task check;
        begin
            #1;
            if (less_result !== (i_a < i_b) || equal_result !== (i_a == i_b))
                $fatal(1, "comparison mismatch width=%0d a=%h b=%h", p_width, i_a, i_b);
            count=count+1;
        end
    endtask
    initial begin
        for (integer sample=0; sample<128; sample=sample+1) begin
            for (integer bit_index=0; bit_index<p_width; bit_index=bit_index+1) begin
                random_state=random_state ^ (random_state << 13);
                random_state=random_state ^ (random_state >> 17);
                random_state=random_state ^ (random_state << 5);
                i_a[bit_index]=random_state[0];
                i_b[bit_index]=random_state[1];
            end
            check();
            for (integer bit_index=0; bit_index<p_width; bit_index=bit_index+1) begin
                i_a[bit_index]=1'bx; check();
                i_a[bit_index]=1'bz; check();
                i_a[bit_index]=i_b[bit_index];
                i_b[bit_index]=1'bx; check();
                i_b[bit_index]=1'bz; check();
                i_b[bit_index]=i_a[bit_index];
            end
        end
        $display("PASS width=%0d checks=%0d", p_width, count);
        $finish;
    end
endmodule
''')
    four_state = []
    for width in WIDTHS:
        executable = out / f'four_state_w{width}.vvp'
        subprocess.run(['iverilog', '-g2012', '-s', 'tb_four_state',
                        f'-Ptb_four_state.p_width={width}', '-o', str(executable),
                        str(source), str(testbench)], check=True)
        result = subprocess.run(['vvp', str(executable)], capture_output=True, text=True, check=True)
        four_state.append({'width': width, 'checks': 128 * (1 + 4 * width),
                           'passed': 'PASS width=' in result.stdout})
    summary['four_state'] = four_state
    summary['passed'] = all(x['passed'] for x in summary['runs'] + four_state)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
