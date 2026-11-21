#!/usr/bin/env python3
"""证明前端短位宽完整求和及事件仿真的分组进位传播。"""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def between(text, start, stop):
    first = text.index(start)
    return text[first:text.index(stop, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.source_root/'rtl/npu/conv/conv_im2col_frontend.sv'
    helper = args.source_root/'rtl/common/parallel_prefix_add.sv'
    text = path.read_text()
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, helper)}
    setting = between(text, '`ifdef ASIC_SYNTHESIS\n  localparam bit p_short_sum_dsp', '  conv_cfg_t c;')
    row = between(text, '    if (p_short_sum_dsp) begin : g_row_bias_arithmetic', '    assign limit_reached')
    history = between(text, '  if (p_short_sum_dsp) begin : g_history_arithmetic', '  logic [17:0] history_reduce_i_a')
    source = args.out/'short_sums.sv'
    source.write_text('''module proof(input logic[15:0]last_x,p_delta,
 input logic[17:0]retire_i_a,retire_i_b,input logic retire_i_carry,
 output logic equivalent);
 logic[16:0]p_sum,reference_history;
 logic unused_p_sum_carry,reference_history_carry;
 logic[17:0]biased_row,reference_row;
 logic unused_row_carry,reference_row_carry;
''' + setting + row + history + '''
 parallel_prefix_add #(.p_width(17),.p_group_width(4),.p_preserve_groups(1'b1)) u_reference_history(
  .i_a({1'b0,last_x}),.i_b({1'b0,p_delta}),.i_carry(1'b0),
  .o_sum(reference_history),.o_carry(reference_history_carry));
 parallel_prefix_add #(.p_width(18),.p_group_width(4),.p_preserve_groups(1'b1)) u_reference_row(
  .i_a(retire_i_a),.i_b(retire_i_b),.i_carry(retire_i_carry),
  .o_sum(reference_row),.o_carry(reference_row_carry));
 assign equivalent=({unused_p_sum_carry,p_sum}==={reference_history_carry,reference_history})&&
   ({unused_row_carry,biased_row}==={reference_row_carry,reference_row});
endmodule
''')
    script, log = args.out/'proof.ys', args.out/'proof.log'
    script.write_text('read_slang --top proof -DSYNTHESIS=1 -DXILINX_FPGA=1 ' +
                      shlex.join([str(source), str(helper)]) +
                      '\nprep -top proof -flatten\ncheck -assert\n'
                      'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
    with log.open('w') as stream:
        run = subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'),
                              '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
                             timeout=120)
    if run.returncode or 'SUCCESS!' not in log.read_text():
        raise RuntimeError(str(log))
    tb = args.out/'four_state.sv'
    tb.write_text('''module tb;
 logic[15:0]last_x,p_delta;
 logic[17:0]retire_i_a,retire_i_b;
 logic retire_i_carry;
 wire equivalent;
 proof dut(.*);
 integer checks=0;
 reg[68:0]pattern;
 initial begin
  for(integer sample=0;sample<20000;sample++)begin
   pattern={$random,$random,$random};
   if(sample%3==0)pattern[sample%69]=1'bx;
   if(sample%5==0)pattern[(sample*7)%69]=1'bz;
   {last_x,p_delta,retire_i_a,retire_i_b,retire_i_carry}=pattern;
   #1;
   if(equivalent!==1'b1)$fatal(1,"short sum propagation");
   checks++;
  end
  $display("SHORT_SUM_FOUR_STATE_PASS checks=%0d",checks);$finish;
 end
endmodule
''')
    rows = []
    for name, defines in [('generic', []), ('fpga', ['-DXILINX_FPGA=1']),
                          ('asic', ['-DASIC_SYNTHESIS=1'])]:
        binary = args.out/(name+'.vvp')
        subprocess.run(['/home/agent/.local/bin/iverilog', '-g2012', '-s', 'tb',
                        *defines, '-o', str(binary), str(source), str(helper), str(tb)],
                       capture_output=True, check=True)
        run = subprocess.run(['/home/agent/.local/bin/vvp', str(binary)],
                             capture_output=True, text=True, check=True, timeout=30)
        sim_log = args.out/(name+'.log')
        sim_log.write_text(run.stdout + run.stderr)
        if 'checks=20000' not in run.stdout:
            raise RuntimeError('Simulation coverage')
        rows.append({'mode': name, 'passed': True, 'samples': 20000,
                     'log_sha256': hashlib.sha256(sim_log.read_bytes()).hexdigest()})
    if hashes != {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (path, helper)}:
        raise RuntimeError('Source changed during verification')
    report = {'passed': True, 'source_sha256': hashes,
              'arithmetic_result_bits': [18, 19], 'binary_input_constraints': [],
              'synthesis_configuration': ['SYNTHESIS=1', 'XILINX_FPGA=1'],
              'full_binary_equivalence': True, 'four_state': rows,
              'formal_log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}
    (args.out/'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print('SHORT_SUM_PASS', report)


if __name__ == '__main__':
    main()
