#!/usr/bin/env python3
"""检查五位除三解码的全部二态及四态输入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root / 'rtl/npu/conv/conv_im2col_frontend.sv'
    text = source.read_text()
    actual = '\n'.join(re.search(pattern, text, re.S)[0] for pattern in (
        r'  assign q_decode_o_quotient = .*?;', r'  assign q_decode_o_remainder = .*?;'))
    decode_function = re.search(r'  function automatic logic \[5:0\] divide_three_5.*?endfunction', text, re.S)
    if decode_function is not None:
        actual = decode_function[0] + '\nlogic [5:0] q_decode_value;\n' + re.search(
            r'  assign q_decode_value = .*?;', text, re.S)[0] + '\n' + actual
    proof = out / 'proof.sv'
    proof.write_text('''module small_decode_proof (
    input logic [31:0] q0,
    output logic equivalent
);
    logic [3:0] q_decode_o_quotient;
    logic [1:0] q_decode_o_remainder;
''' + actual + '''
    logic [8:0] scaled;
    logic [3:0] reference_quotient;
    logic [1:0] reference_remainder;
    assign scaled={1'b0,q0[4:0],3'b000}+{3'b000,q0[4:0],1'b0}+{4'b0000,q0[4:0]};
    assign reference_quotient=scaled[8:5];
    assign reference_remainder=q0[1:0]+reference_quotient[1:0];
    assign equivalent=(q_decode_o_quotient==reference_quotient) &&
                      (q_decode_o_remainder==reference_remainder);
endmodule
''')
    script = out / 'proof.ys'
    script.write_text('read_slang --top small_decode_proof ' + shlex.quote(str(proof)) + '\n' +
                      'prep -top small_decode_proof -flatten\nmemory_map\nopt\ncheck -assert\n' +
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with (out / 'proof.log').open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                        '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT, check=True)
    assert 'SUCCESS' in (out / 'proof.log').read_text()
    tb = out / 'decode.sv'
    tb.write_text('''module tb_decode;
    reg [31:0] q0;
    wire [3:0] q_decode_o_quotient;
    wire [1:0] q_decode_o_remainder;
''' + actual + '''
    wire [8:0] scaled = {1'b0,q0[4:0],3'b000} +
        {3'b000,q0[4:0],1'b0} + {4'b0000,q0[4:0]};
    wire [3:0] reference_quotient=scaled[8:5];
    wire [1:0] reference_remainder=q0[1:0]+reference_quotient[1:0];
    integer sample, bit_index, digit, expected_quotient, expected_remainder;
    initial begin
        for (sample=0;sample<32;sample=sample+1) begin
            q0=sample;
            expected_quotient=sample/3;
            expected_remainder=sample-expected_quotient*3;
            #1;
            if (q_decode_o_quotient!==4'(expected_quotient) ||
                q_decode_o_remainder!==2'(expected_remainder))
                $fatal(1,"binary decode sample %0d",sample);
        end
        for (sample=0;sample<1024;sample=sample+1) begin
            q0=0;
            for (bit_index=0;bit_index<5;bit_index=bit_index+1) begin
                digit=(sample>>(2*bit_index))&3;
                case (digit)
                    0:q0[bit_index]=1'b0;
                    1:q0[bit_index]=1'b1;
                    2:q0[bit_index]=1'bx;
                    3:q0[bit_index]=1'bz;
                endcase
            end
            #1;
            if (q_decode_o_quotient!==reference_quotient ||
                q_decode_o_remainder!==reference_remainder)
                $fatal(1,"four-state decode sample %0d",sample);
        end
        $display("SMALL_DECODE_PASS binary=32 four_state=1024");
        $finish;
    end
endmodule
''')
    binary = out / 'decode.vvp'
    with (out / 'compile.log').open('w') as stream:
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb_decode',
                        '-o', str(binary), str(tb)], stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)],
                            capture_output=True, text=True, check=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    assert 'SMALL_DECODE_PASS' in result.stdout
    summary = {'passed': True, 'sat_passed': True, 'input_constraints': [],
               'binary_inputs': 32, 'four_state_inputs': 1024,
               'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'test_sha256': hashlib.sha256(tb.read_bytes()).hexdigest()}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(result.stdout.strip())


if __name__ == '__main__':
    main()
