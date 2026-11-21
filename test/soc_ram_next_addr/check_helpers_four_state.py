#!/usr/bin/env python3
"""记录实际容量比较和字节通道选择对 X/Z 输入的逐位传播。"""
import argparse
import json
import math
from pathlib import Path
import subprocess
from common import ROOT, REFERENCE, digest, snapshot, helper_miter

PROFILES = [(8, 8, 1), (8, 32, 3), (8, 64, 32), (8, 64, 64),
            (16, 24, 1031), (16, 128, 1024), (32, 64, 32768), (40, 1024, 32769)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default=REFERENCE)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    _, inputs = snapshot(out / 'inputs', args.reference, args.source_root, args.reference_root)
    model = out / 'helper_miter.sv'
    model.write_text(helper_miter(args.reference, args.source_root, args.reference_root))
    instances, reports = [], []
    count, maximum_result = len(PROFILES), max(dw // 8 + 2 for _, dw, _ in PROFILES)
    for index, (aw, dw, dp) in enumerate(PROFILES):
        width = dw // 8 + 2
        word_top = aw - (math.ceil(math.log2(dw // 8)) if dw > 8 else 0)
        instances.append(f'''    helper_miter #(.AW({aw}),.DW({dw}),.DP({dp})) u{index}(
        .rd_issue_word_addr(read_word[{word_top}:0]),.wr_word_addr_q(write_word[{word_top}:0]),
        .wr_byte_addr_q(address[{aw}:0]),.wr_size_active_q(size),
        .reference_result(reference_result[{index}][{width-1}:0]),
        .current_result(current_result[{index}][{width-1}:0]),.correct());''')
        if width < maximum_result:
            instances.append(f"    assign reference_result[{index}][{maximum_result-1}:{width}]='0;\n"
                             f"    assign current_result[{index}][{maximum_result-1}:{width}]='0;")
        fields = ['equal_results', 'unknown_to_known_bits', 'known_to_unknown_bits', 'known_bit_conflicts']
        template = json.dumps({'address_width': aw, 'data_width': dw, 'memory_words': dp,
                               'samples': 4096, **{field: '%0d' for field in fields}}).replace('"%0d"', '%0d')
        reports.append('        $display("RESULT ' + template.replace('"', '\\"') + '",' +
                       ','.join(f'{field}[{index}]' for field in fields) + ');')
    bench = out / 'tb.sv'
    bench.write_text(f'''module tb;
    reg [40:0] address,read_word,write_word;
    reg [2:0] size;
    wire [{maximum_result-1}:0] reference_result[{count}],current_result[{count}];
    integer equal_results[{count}],unknown_to_known_bits[{count}];
    integer known_to_unknown_bits[{count}],known_bit_conflicts[{count}];
''' + '\n'.join(instances) + f'''
    initial begin
        for(integer n=0;n<{count};n++)begin
            equal_results[n]=0;unknown_to_known_bits[n]=0;
            known_to_unknown_bits[n]=0;known_bit_conflicts[n]=0;
        end
        for(integer sample=0;sample<4096;sample++)begin
            address={{$urandom,$urandom}};read_word={{$urandom,$urandom}};
            write_word={{$urandom,$urandom}};size=3'(sample);
            if(sample<512)begin
                address=41'(sample);read_word=41'(sample);write_word=41'(511-sample);
            end
            if(sample>=1024)begin
                case(sample%8)
                    0:address[(sample/8)%41]=1'bx;
                    1:address[(sample/8)%41]=1'bz;
                    2:read_word[(sample/8)%41]=1'bx;
                    3:read_word[(sample/8)%41]=1'bz;
                    4:write_word[(sample/8)%41]=1'bx;
                    5:write_word[(sample/8)%41]=1'bz;
                    6:size[(sample/8)%3]=1'bx;
                    7:size[(sample/8)%3]=1'bz;
                endcase
            end
            #1;
            for(integer n=0;n<{count};n++)begin
                if(reference_result[n]===current_result[n])equal_results[n]++;
                for(integer b=0;b<{maximum_result};b++)begin
                    if(reference_result[n][b]!==current_result[n][b])begin
                        if(reference_result[n][b]===1'b0 || reference_result[n][b]===1'b1)begin
                            if(current_result[n][b]===1'b0 || current_result[n][b]===1'b1)known_bit_conflicts[n]++;
                            else known_to_unknown_bits[n]++;
                        end else if(current_result[n][b]===1'b0 || current_result[n][b]===1'b1)unknown_to_known_bits[n]++;
                    end
                end
                if(sample<1024 && reference_result[n]!==current_result[n])
                    $fatal(1,"Known helper input differs sample=%0d profile=%0d",sample,n);
            end
        end
''' + '\n'.join(reports) + f'''
        for(integer n=0;n<{count};n++)begin
            if(known_bit_conflicts[n]!=0 || known_to_unknown_bits[n]!=0)
                $fatal(1,"Known reference helper bit changed profile=%0d",n);
        end
        $display("SOC_RAM_HELPERS_FOUR_STATE_PASS");$finish;
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
    assert 'SOC_RAM_HELPERS_FOUR_STATE_PASS' in result.stdout
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
