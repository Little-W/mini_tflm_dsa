#!/usr/bin/env python3
"""比较实际地址函数的已知结果，并统计 X/Z 输入的逐位传播。"""
import argparse
import json
from pathlib import Path
import subprocess
from common import REFERENCE, WIDTHS, digest, snapshot, miter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    args = parser.parse_args()
    out = args.out.resolve()
    functions, inputs = snapshot(out / 'inputs', args.reference)
    model = out / 'miter.sv'
    model.write_text(miter(*functions))
    instances, reports = [], []
    count, maximum_width = len(WIDTHS), max(WIDTHS) + 1
    for index, aw in enumerate(WIDTHS):
        instances.append(f'''    address_miter #(.AW({aw})) u{index}(
        .byte_addr(address[{aw}:0]), .size(size), .burst(burst),
        .reference_address(reference_address[{index}][{aw}:0]),
        .current_address(current_address[{index}][{aw}:0]), .correct());''')
        if aw + 1 < maximum_width:
            instances.append(f"    assign reference_address[{index}][{maximum_width-1}:{aw+1}] = '0;\n"
                             f"    assign current_address[{index}][{maximum_width-1}:{aw+1}] = '0;")
        fields = ['equal_results', 'unknown_to_known_bits', 'known_to_unknown_bits', 'known_bit_conflicts']
        template = json.dumps({'address_width': aw, 'samples': 65536,
                               **{field: '%0d' for field in fields}}).replace('"%0d"', '%0d')
        reports.append('        $display("RESULT ' + template.replace('"', '\\"') + '",' +
                       ','.join(f'{field}[{index}]' for field in fields) + ');')
    bench = out / 'tb.sv'
    bench.write_text(f'''module tb;
    reg [{maximum_width-1}:0] address;
    reg [2:0] size;
    reg [1:0] burst;
    wire [{maximum_width-1}:0] reference_address[{count}], current_address[{count}];
    integer equal_results[{count}], unknown_to_known_bits[{count}];
    integer known_to_unknown_bits[{count}], known_bit_conflicts[{count}];
''' + '\n'.join(instances) + f'''
    initial begin
        for (integer n=0; n<{count}; n++) begin
            equal_results[n]=0; unknown_to_known_bits[n]=0;
            known_to_unknown_bits[n]=0; known_bit_conflicts[n]=0;
        end
        for (integer sample=0; sample<65536; sample++) begin
            address={{$urandom, $urandom, $urandom}};
            size=3'(sample); burst=2'(sample/8);
            if (sample<2048) begin
                case ((sample/32)%4)
                    0: address='0;
                    1: address='1;
                    2: address=({maximum_width}'(1) << ((sample/128)%{maximum_width})) - 1'b1;
                    3: address=({maximum_width}'(1) << ((sample/128)%{maximum_width}));
                endcase
            end
            if (sample>=16384) begin
                case (sample%6)
                    0: address[(sample/6)%{maximum_width}]=1'bx;
                    1: address[(sample/6)%{maximum_width}]=1'bz;
                    2: size[(sample/6)%3]=1'bx;
                    3: size[(sample/6)%3]=1'bz;
                    4: burst[(sample/6)%2]=1'bx;
                    5: burst[(sample/6)%2]=1'bz;
                endcase
            end
            #1;
            for (integer n=0; n<{count}; n++) begin
                if (reference_address[n]===current_address[n]) equal_results[n]++;
                for (integer b=0; b<{maximum_width}; b++) begin
                    if (reference_address[n][b]!==current_address[n][b]) begin
                        if ((reference_address[n][b]===1'b0) || (reference_address[n][b]===1'b1)) begin
                            if ((current_address[n][b]===1'b0) || (current_address[n][b]===1'b1))
                                known_bit_conflicts[n]++;
                            else known_to_unknown_bits[n]++;
                        end else if ((current_address[n][b]===1'b0) || (current_address[n][b]===1'b1))
                            unknown_to_known_bits[n]++;
                    end
                end
                if (sample<16384 && reference_address[n]!==current_address[n])
                    $fatal(1,"Known-input result differs, sample=%0d profile=%0d",sample,n);
            end
        end
''' + '\n'.join(reports) + f'''
        for (integer n=0; n<{count}; n++) begin
            if (known_bit_conflicts[n]!=0 || known_to_unknown_bits[n]!=0)
                $fatal(1,"Known reference bit changed, profile=%0d",n);
        end
        $display("SOC_RAM_NEXT_ADDRESS_FOUR_STATE_PASS");
        $finish;
    end
endmodule
''')
    with (out / 'compile.log').open('w') as log:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(out / 'sim'), str(model), str(bench)],
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    result = subprocess.run(['vvp', str(out / 'sim')], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    assert 'SOC_RAM_NEXT_ADDRESS_FOUR_STATE_PASS' in result.stdout
    rows = [json.loads(line.removeprefix('RESULT ')) for line in result.stdout.splitlines()
            if line.startswith('RESULT ')]
    assert len(rows) == count
    report = {'passed': True, 'inputs': inputs, 'profiles': rows,
              'four_state_equivalent': all(row['equal_results'] == row['samples'] for row in rows),
              'defined_binary_input_behavior': 'proven equal separately by complete-input SAT',
              'total_samples': sum(row['samples'] for row in rows),
              'total_known_bit_conflicts': sum(row['known_bit_conflicts'] for row in rows),
              'total_unknown_to_known_bits': sum(row['unknown_to_known_bits'] for row in rows),
              'total_known_to_unknown_bits': sum(row['known_to_unknown_bits'] for row in rows),
              'miter_sha256': digest(model), 'testbench_sha256': digest(bench),
              'log_sha256': digest(out / 'run.log')}
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in
                     ['passed', 'total_samples', 'four_state_equivalent', 'total_unknown_to_known_bits']}))


if __name__ == '__main__':
    main()
