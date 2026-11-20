#!/usr/bin/env python3
"""穷举四态分母地址，比较同步读取和原常量表的同周期结果。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--formal-out', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    reference = args.formal_out.resolve()/'reference.sv'
    current = args.formal_out.resolve()/'current.sv'
    old = out/'reference.sv'
    old.write_text(reference.read_text().replace('module reciprocal_unit #(', 'module reciprocal_reference #(', 1))
    testbench = out/'testbench.sv'
    testbench.write_text('''module testbench;
logic clk;
logic [8:0] address;
logic [17:0] expected, actual;
integer combination, work_value, digit;
reciprocal_reference reference (.clk(clk),.i_taps(address),.o_reciprocal(expected));
reciprocal_unit current (.clk(clk),.i_taps(address),.o_reciprocal(actual));
initial begin
  clk=0;address=0;
  for (combination=0;combination<262144;combination=combination+1) begin
    work_value=combination;
    for (integer bit_index=0;bit_index<9;bit_index=bit_index+1) begin
      digit=work_value%4;
      case(digit)
        0: address[bit_index]=1'b0;
        1: address[bit_index]=1'b1;
        2: address[bit_index]=1'bx;
        3: address[bit_index]=1'bz;
      endcase
      work_value=work_value/4;
    end
    #1;clk=1;#1;
    if(actual !== expected) $fatal(1,"倒数表四态读取结果不同 address=%b expected=%h actual=%h",address,expected,actual);
    clk=0;
  end
  $display("RECIPROCAL_FOUR_STATE_PASS checks=262144");
  $finish;
end
endmodule
''')
    runs = []
    for mode, defines in (('fpga', []), ('asic', ['-DASIC_SYNTHESIS'])):
        executable = out/(mode+'.vvp')
        with (out/(mode+'_build.log')).open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-s', 'testbench', *defines, '-o', str(executable),
                            str(old), str(current), str(testbench)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        log = out/(mode+'.log')
        with log.open('w') as stream:
            subprocess.run(['vvp', str(executable)], stdout=stream, stderr=subprocess.STDOUT, check=True)
        if 'RECIPROCAL_FOUR_STATE_PASS checks=262144' not in log.read_text():
            raise RuntimeError('四态地址检查未完成')
        runs.append({'mode': mode, 'passed': True, 'four_state_addresses': 262144,
                     'defined_addresses': 257, 'out_of_range_defined_bit_patterns': 255,
                     'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()})
    summary = {'passed': True, 'runs': runs,
               'source_sha256': {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (reference, current, Path(__file__).resolve())}}
    (out/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
