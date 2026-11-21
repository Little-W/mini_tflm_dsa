#!/usr/bin/env python3
"""Check known output bits of actual IS group arithmetic with X/Z input values."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from run_formal import ROOT, extract, read_rtl_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference', default='2297cb12')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/top/npu_top.sv'
    current = source.read_text()
    original = read_rtl_source(args.reference + ':rtl/npu/top/npu_top.sv', cwd=ROOT, text=True)
    modules = out / 'arithmetic.sv'
    modules.write_text(((ROOT / 'rtl/common/unsigned_compare.sv').read_text() +
                       extract(original, 'reference') + extract(current, 'candidate'))
                       .replace('localparam int unsigned', 'localparam integer')
                       .replace('parameter int unsigned', 'parameter integer'))
    results = []
    for width, count in ((16,8), (32,10), (64,20)):
        bits = width + 2*count
        bench = out / f'tb_{width}_{count}.sv'
        bench.write_text(f'''module tb;
    reg [31:0] exec_m;
    reg [{count-1}:0] is_bias_group_rows_target;
    wire [{bits-1}:0] expected, actual;
    integer equal_count=0, refined_bits=0, known_bits=0;
    reference #(.REG_WIDTH({width}),.IS_BIAS_VALID_W({count})) r
        (.exec_m(exec_m),.is_bias_group_rows_target(is_bias_group_rows_target),.result(expected));
    candidate #(.REG_WIDTH({width}),.IS_BIAS_VALID_W({count})) c
        (.exec_m(exec_m),.is_bias_group_rows_target(is_bias_group_rows_target),.result(actual));
    initial begin
        for (integer sample=0;sample<32768;sample=sample+1) begin
            exec_m=$urandom;
            is_bias_group_rows_target={count}'($urandom);
            if (sample<4096) begin
                is_bias_group_rows_target={count}'(1) << (sample%{count});
                case ((sample/{count})%6)
                    0: exec_m=0;
                    1: exec_m=32'(is_bias_group_rows_target);
                    2: exec_m=32'(is_bias_group_rows_target)-1;
                    3: exec_m=32'(is_bias_group_rows_target)+1;
                    4: exec_m='1;
                    5: is_bias_group_rows_target=0;
                endcase
            end
            if (sample>=8192) begin
                case (sample%4)
                    0: exec_m[(sample/4)%32]=1'bx;
                    1: exec_m[(sample/4)%32]=1'bz;
                    2: is_bias_group_rows_target[(sample/4)%{count}]=1'bx;
                    3: is_bias_group_rows_target[(sample/4)%{count}]=1'bz;
                endcase
            end
            #1;
            if (expected===actual) equal_count++;
            for (integer bit_idx=0;bit_idx<{bits};bit_idx=bit_idx+1) begin
                if (expected[bit_idx]===1'b0 || expected[bit_idx]===1'b1) begin
                    known_bits++;
                    if (expected[bit_idx]!==actual[bit_idx])
                        $fatal(1,"Known result differs, sample=%0d bit=%0d",sample,bit_idx);
                end else if (actual[bit_idx]===1'b0 || actual[bit_idx]===1'b1) refined_bits++;
            end
        end
        $display("PASS equal=%0d known=%0d refined=%0d",equal_count,known_bits,refined_bits);
        $finish;
    end
endmodule
''')
        executable = out / f'sim_{width}_{count}'
        with (out/f'compile_{width}_{count}.log').open('w') as log:
            subprocess.run(['iverilog','-g2012','-s','tb','-o',str(executable),str(modules),str(bench)],
                           stdout=log, stderr=subprocess.STDOUT,check=True)
        run = subprocess.run(['vvp',str(executable)],capture_output=True,text=True,check=True)
        (out/f'run_{width}_{count}.log').write_text(run.stdout+run.stderr)
        line=next(x for x in run.stdout.splitlines() if x.startswith('PASS '))
        fields={k:int(v) for k,v in (x.split('=') for x in line.split()[1:])}
        results.append(dict(width=width,count_bits=count,samples=32768,**fields))
        print(results[-1],flush=True)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    if source.read_text()!=current:
        raise RuntimeError('Top source changed during verification')
    report=dict(passed=True,source_sha256=hashlib.sha256(current.encode()).hexdigest(),extracted_sha256=digest(modules),
                reference=args.reference,known_reference_bits_preserved=True,runs=results)
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':
    main()
