#!/usr/bin/env python3
"""验证分段进位选择的完整和值、最高进位与四态传播。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def unit(width: int, group: int, split: int) -> str:
    return f'''module comparison(input logic[{width-1}:0] i_a,i_b,
input logic i_carry,output logic equivalent);
wire[{width}:0] observed,reference_value;
wire[{width}:0] expected={{1'b0,i_a}}+{{1'b0,i_b}}+{width+1}'(i_carry);
parallel_prefix_add #(.p_width({width}),.p_group_width({group}),.p_preserve_groups(1'b1),
  .p_carry_select_width({split})) u_candidate(.i_a,.i_b,.i_carry,
    .o_sum(observed[{width-1}:0]),.o_carry(observed[{width}]));
parallel_prefix_add #(.p_width({width}),.p_group_width({group}),.p_preserve_groups(1'b1))
  u_reference(.i_a,.i_b,.i_carry,.o_sum(reference_value[{width-1}:0]),.o_carry(reference_value[{width}]));
`ifdef SYNTHESIS
assign equivalent=(observed==expected)&&(observed==reference_value);
`else
assign equivalent=observed===reference_value;
`endif
endmodule
'''


def bench(width: int) -> str:
    return f'''module tb;
logic[{2*width}:0] stimulus,known_stimulus;
wire[{width-1}:0] i_a=stimulus[{width-1}:0],i_b=stimulus[{2*width-1}:{width}];
wire i_carry=stimulus[{2*width}];
wire equivalent;
integer checks=0;
comparison dut(.*);
task automatic check;
  #1;if(equivalent!==1'b1)$fatal(1,"carry-select mismatch check=%0d",checks);
  checks++;
endtask
initial begin
  for(int trial=0;trial<32;trial++)begin
    for(int bit_index=0;bit_index<{2*width+1};bit_index++)stimulus[bit_index]=$urandom_range(0,1);
    known_stimulus=stimulus;check();
    for(int bit_index=0;bit_index<{2*width+1};bit_index++)begin
      stimulus=known_stimulus;stimulus[bit_index]=1'bx;check();
      stimulus=known_stimulus;stimulus[bit_index]=1'bz;check();
    end
    stimulus='x;check();stimulus='z;check();
  end
  $display("CARRY_SELECT_FOUR_STATE_PASS checks=%0d",checks);$finish;
end
endmodule
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--iverilog', default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp', default=shutil.which('vvp') or 'vvp')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    helper = args.source_root.resolve() / 'rtl/common/parallel_prefix_add.sv'
    local = out / helper.name
    local.write_text(helper.read_text().replace('parameter int unsigned', 'parameter integer'))
    report = {'passed': False, 'source_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(),
              'input_assumptions': [], 'cases': []}
    for width in (1, 7, 8, 9, 16, 17, 32, 33, 35, 64):
        for group in (4, 8):
            for split in (1, 8, 16):
                folder = out / f'w{width}_g{group}_s{split}'
                folder.mkdir(exist_ok=True)
                rtl = folder / 'formal.sv'
                rtl.write_text(unit(width, group, split))
                script = folder / 'proof.ys'
                script.write_text('read_slang --top comparison -D SYNTHESIS=1 ' +
                                  shlex.join(map(str, (helper, rtl))) + '\n' +
                                  'prep -top comparison -flatten\nopt\n' +
                                  'sat -set-def-inputs -prove equivalent 1 -verify\n')
                with (folder / 'proof.log').open('w') as log:
                    subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
                                    '--worker', str(script)], stdout=log, stderr=subprocess.STDOUT,
                                   check=True, timeout=180)
                rtl = folder / 'simulation.sv'
                rtl.write_text(unit(width, group, split) + bench(width))
                binary = folder / 'run.vvp'
                with (folder / 'build.log').open('w') as log:
                    subprocess.run([args.iverilog, '-g2012', '-s', 'tb', '-o', str(binary),
                                    str(local), str(rtl)], stdout=log, stderr=subprocess.STDOUT, check=True)
                with (folder / 'run.log').open('w') as log:
                    subprocess.run([args.vvp, str(binary)], stdout=log, stderr=subprocess.STDOUT, check=True)
                summary = (folder / 'run.log').read_text().strip()
                if 'CARRY_SELECT_FOUR_STATE_PASS' not in summary:
                    raise AssertionError(summary)
                report['cases'].append({'width': width, 'group_width': group, 'select_width': split,
                                        'formal_passed': True, 'four_state_passed': True, 'summary': summary})
                print(folder.name + ': PASS', flush=True)
    report['sources_unchanged'] = report['source_sha256'] == hashlib.sha256(helper.read_bytes()).hexdigest()
    if not report['sources_unchanged']:
        raise RuntimeError('Carry-select source changed during validation')
    report['passed'] = True
    (out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
