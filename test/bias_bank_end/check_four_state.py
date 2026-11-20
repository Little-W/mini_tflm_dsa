#!/usr/bin/env python3
"""检查实际银行末端加法边界的四态输出传播。"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from prove import ROOT, BUFFER, HELPER, digest, arithmetic_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = (ROOT / BUFFER).read_text()
    reference = arithmetic_reference(source)
    start = source.index('  logic [CNT_W:0] bank_end_i_a, bank_end_i_b, bank_end_o_sum;')
    end = source.index('  logic                         load_bank_q;', start)
    block = source[start:end]
    expression = re.search(r'bank_end_q\[load_bank\] <= ([^;]+);', reference)[1]
    model = out / 'bank_sum.sv'
    model.write_text('''module bank_sum #(parameter CNT_W=29)(
    input logic [CNT_W-1:0] load_block_idx,load_blocks_count,
    output wire [CNT_W:0] reference_sum,current_sum);
''' + block + '\n  assign reference_sum=' + expression + ';\n  assign current_sum=bank_end_o_sum;\nendmodule\n')
    bench = out / 'tb.sv'
    instances = []
    widths = [1, 8, 12, 29, 32]
    for i, width in enumerate(widths):
        instances.append(f'  bank_sum #(.CNT_W({width})) u{i}(.load_block_idx(a[{width-1}:0]),'
                         f'.load_blocks_count(b[{width-1}:0]),.reference_sum(reference_sum[{i}][{width}:0]),'
                         f'.current_sum(current_sum[{i}][{width}:0]));')
        if width < 32:
            instances.append(f"  assign reference_sum[{i}][32:{width+1}]='0;\n"
                             f"  assign current_sum[{i}][32:{width+1}]='0;")
    bench.write_text('''module tb;
  logic [31:0] a,b;
  wire [32:0] reference_sum[5],current_sum[5];
  integer seed=32'h179c4a02;
  integer known_bits=0,refined_bits=0,unknown_bits=0;
''' + '\n'.join(instances) + '''
  initial begin
    for(integer n=0;n<8192;n=n+1) begin
      a=$random(seed);b=$random(seed);
      if(n<128)begin a=32'(n);b=~a;end
      if(n>=2048)begin
        case(n%4)
          0:a[(n/4)%32]=1'bx;
          1:a[(n/4)%32]=1'bz;
          2:b[(n/4)%32]=1'bx;
          3:b[(n/4)%32]=1'bz;
        endcase
      end
      #1;
      for(integer profile=0;profile<5;profile=profile+1)begin
        for(integer bit_i=0;bit_i<33;bit_i=bit_i+1)begin
          if(reference_sum[profile][bit_i]===1'b0 || reference_sum[profile][bit_i]===1'b1)begin
            known_bits=known_bits+1;
            if(reference_sum[profile][bit_i]!==current_sum[profile][bit_i])
              $fatal(1,"Known bank sum bit changed sample=%0d profile=%0d bit=%0d",n,profile,bit_i);
          end else if(current_sum[profile][bit_i]===1'b0 || current_sum[profile][bit_i]===1'b1)
            refined_bits=refined_bits+1;
          else unknown_bits=unknown_bits+1;
        end
      end
    end
    $display("FOUR_STATE_PASS known_bits=%0d refined_bits=%0d unknown_bits=%0d",known_bits,refined_bits,unknown_bits);
    $finish;
  end
endmodule
''')
    helper = out / 'parallel_prefix_add.sv'
    helper.write_bytes((ROOT / HELPER).read_bytes())
    with (out / 'build.log').open('w') as stream:
        subprocess.run(['iverilog', '-g2012', '-s', 'tb', '-o', str(out / 'simulation.vvp'),
                        str(model), str(helper), str(bench)], check=True, stdout=stream, stderr=subprocess.STDOUT)
    result = subprocess.run(['vvp', str(out / 'simulation.vvp')], capture_output=True, text=True)
    (out / 'run.log').write_text(result.stdout + result.stderr)
    match = re.search(r'FOUR_STATE_PASS known_bits=(\d+) refined_bits=(\d+) unknown_bits=(\d+)', result.stdout)
    assert result.returncode == 0 and match, result.stdout + result.stderr
    report = {'passed': True, 'source': BUFFER, 'source_sha256': digest(ROOT / BUFFER),
              'helper_sha256': digest(helper), 'widths': widths, 'samples': 8192 * len(widths),
              **dict(zip(['known_bits', 'refined_bits', 'unknown_bits'], map(int, match.groups()))),
              'property': 'known reference bits preserved; unknown reference bits may resolve',
              'universal_four_state_equivalence_claimed': False,
              'model_sha256': digest(model), 'testbench_sha256': digest(bench),
              'run_log_sha256': digest(out / 'run.log')}
    assert source == (ROOT / BUFFER).read_text() and digest(helper) == digest(ROOT / HELPER)
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ['passed', 'samples', 'known_bits', 'refined_bits', 'unknown_bits']}))


if __name__ == '__main__':
    main()
