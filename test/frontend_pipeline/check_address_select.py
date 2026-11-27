#!/usr/bin/env python3
"""比较实际描述符候选选择与完整地址优先次序。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys

import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]
FLAGS = ('incoming_window_context', 'incoming_position_same_tap',
         'incoming_position_previous_row', 'incoming_position_forward_tap',
         'incoming_position_backward_tap', 'o_incoming_next_tile_fast',
         'o_incoming_skip_tap', 'incoming_q_equal', 'i_incoming_tap_wrap')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'rtl/npu/conv/conv_im2col_descriptor.sv'
    text = source.read_text()
    first = text.index('  assign incoming_word_flags[9]')
    flags = text[first:text.index('  assign incoming_padding_flags[5]', first)]
    first = text.index('  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_word_choice')
    choice = text[first:text.index('  for (genvar candidate = 0; candidate < 9; candidate++) begin : g_padding_choice', first)]
    first = text.index('  if (p_register_descriptor) begin : g_prepared_first_address')
    mux = text[first:text.index('  end else assign incoming_address_selected', first)] + '  end\n'
    first = text.index('      case (^{incoming_window_context, incoming_position_same_tap')
    select = text[first:text.index('      endcase', first) + len('      endcase')]
    select = re.sub(r'\bo_incoming_addr\b', 'actual', select)
    ports = [(name, 1, '') for name in FLAGS] + [
        ('i_kx0_q', 16, '[15:0]'), ('o_incoming_address_candidates', 320, '[9:0][31:0]')]
    declarations = '\n'.join('logic ' + width + ' ' + name + ';' for name, _, width in ports)
    model = 'module comparison(\n' + ',\n'.join(
        'input logic ' + width + ' ' + name for name, _, width in ports) + ''',
output logic [31:0] actual,expected,output logic equivalent,
output logic [9:0] prepared_word_select);
localparam bit p_register_descriptor=1'b1;
logic [9:0][5:0] incoming_word_flags;
logic [9:0] incoming_word_choice;
logic [31:0] incoming_address_selected;
wire incoming_window_match=incoming_position_same_tap || incoming_position_previous_row ||
    incoming_position_forward_tap || incoming_position_backward_tap;
wire o_incoming_next_position_fast=incoming_window_context && incoming_window_match;
''' + flags + choice + mux + '''
assign prepared_word_select=incoming_word_choice;
always_comb begin
  expected=o_incoming_address_candidates[0];
  if(o_incoming_next_position_fast)begin
    expected=o_incoming_address_candidates[6];
    if(incoming_position_previous_row)expected=o_incoming_address_candidates[9];
    else if(incoming_position_forward_tap)expected=o_incoming_address_candidates[7];
    else if(incoming_position_backward_tap)expected=o_incoming_address_candidates[8];
  end else if(o_incoming_next_tile_fast)expected=o_incoming_address_candidates[5];
  else if(o_incoming_skip_tap)begin
    if(i_kx0_q!=0)expected=o_incoming_address_candidates[4];
    else expected=o_incoming_address_candidates[3];
  end else if(!incoming_q_equal)begin
    if(i_incoming_tap_wrap)expected=o_incoming_address_candidates[2];
    else expected=o_incoming_address_candidates[1];
  end
end
always_comb begin
  actual=expected;
''' + select + '''
end
assign equivalent=actual===expected;
endmodule
'''
    modelpath = out / 'comparison.sv'
    modelpath.write_text(model)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([modelpath], ROOT)
    hashes = {str(p.relative_to(ROOT)): digest(p)
              for p in resolver['input_files'](sources, ROOT) if p.is_relative_to(ROOT)}
    hashes[str(source.relative_to(ROOT))] = digest(source)
    script, log = out / 'formal.ys', out / 'formal.log'
    script.write_text(shlex.join(['read_slang', '--top', 'comparison', '-DSYNTHESIS=1',
        *map(str, sources)]) + '\nsetattr -mod -unset keep_hierarchy\n'
        'setattr -unset keep_hierarchy\nprep -top comparison -flatten\n'
        'sat -verify -prove equivalent 1\n')
    with log.open('w') as stream:
        subprocess.run([sys.executable, str(ROOT / 'scripts/fpga/open_fpga_synth.py'),
            '--worker', str(script)], stdout=stream, stderr=subprocess.STDOUT,
            check=True, timeout=180)
    if 'SUCCESS!' not in log.read_text():
        raise RuntimeError('描述符首地址形式比较未完成')
    names = ','.join(name for name, _, _ in ports)
    widths = {name: bits for name, bits, _ in ports}
    bits = sum(widths.values())
    tb = 'module tb;\n' + declarations + f'''
localparam integer p_input_width={bits};
logic [p_input_width-1:0] stimulus;
logic [31:0] actual,expected;
logic equivalent;
logic [9:0] prepared_word_select;
integer selected_count[10];
assign {{{names}}}=stimulus;
comparison dut(.*);
initial begin
  for(integer i=0;i<10;i++)selected_count[i]=0;
  for(integer sample=0;sample<8192;sample++)begin
    for(integer i=0;i<p_input_width;i++)stimulus[i]=1'($urandom);
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5,6,7:stimulus[sample%p_input_width]=1'bx;
      8,9,10,11:stimulus[sample%p_input_width]=1'bz;
      default:begin end
    endcase
    if(sample%64==17)begin
      stimulus[320+:16]=16'd0;
      stimulus[336+:9]=9'b000000100;
    end
    #1;
    if(equivalent!==1'b1)$fatal(1,"first address mismatch sample=%0d actual=%h expected=%h select=%b flags=%b kx=%h data=%h",sample,actual,expected,prepared_word_select,stimulus[336+:9],i_kx0_q,o_incoming_address_candidates);
    for(integer i=0;i<10;i++)if(prepared_word_select[i]===1'b1)selected_count[i]++;
  end
  for(integer i=0;i<10;i++)if(selected_count[i]==0)$fatal(1,"candidate coverage index=%0d",i);
  $display("ADDRESS_SELECT_FOUR_STATE_PASS samples=8192");
  $finish;
end
endmodule
'''
    tb = tb.replace('initial begin', coverage.declarations('p_input_width') +
        'initial begin' + coverage.initialize('p_input_width', names), 1)
    tb = tb.replace('    #1;', coverage.sample('p_input_width') + '    #1;', 1)
    tb = tb.replace('  $display("ADDRESS_SELECT_FOUR_STATE_PASS',
        coverage.finish('p_input_width') + '  $display("ADDRESS_SELECT_FOUR_STATE_PASS', 1)
    bench, binary = out / 'tb.sv', out / 'tb.vvp'
    bench.write_text(tb)
    four = []
    for synthesis in (False, True):
        simlog = out / f'four_state_{int(synthesis)}.log'
        command = ['iverilog', '-g2012', '-s', 'tb', '-o', str(binary)]
        if synthesis:
            command.append('-DSYNTHESIS=1')
        with simlog.open('w') as stream:
            subprocess.run(command + [*map(str, sources), str(bench)],
                stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            subprocess.run(['vvp', str(binary)], stdout=stream,
                stderr=subprocess.STDOUT, check=True, timeout=180)
        four.append(dict(synthesis=synthesis, comparisons=8192, passed=True,
            coverage=coverage.result(simlog, widths), log_sha256=digest(simlog)))
    if any(digest(ROOT / name) != value for name, value in hashes.items()):
        raise RuntimeError('描述符首地址检查期间源码发生变化')
    (out / 'summary.json').write_text(json.dumps(dict(passed=True,
        formal_properties=1, input_assumptions=[], formal_log_sha256=digest(log),
        four_state=four, source_sha256=hashes), ensure_ascii=False, indent=2) + '\n')
    print('ADDRESS_SELECT_PASS formal=1 four_state=16384', flush=True)


if __name__ == '__main__':
    main()
