#!/usr/bin/env python3
"""验证完整地址匹配、描述符来源选择及保存字转发的组合连接。"""
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
HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT/'rtl/npu/conv/conv_descriptor_addresses.sv'
    reference = HERE/'word_forward_reference.sv'
    if digest(reference) != 'cc1be5debbf705ca097d4926916f743ae374bb5588355cdd42903e5de1bef753':
        raise RuntimeError('完整标签计算参考模型与记录不同')
    ports = re.findall(r'\b(input|output) logic\s+((?:\[[^\]]+\])*)\s*(\w+)\s*(?:,|//)', source.read_text().split(');', 1)[0])
    inputs = [(width, name) for direction, width, name in ports if direction == 'input']
    outputs = [(width, name) for direction, width, name in ports if direction == 'output' and name!='o_word_candidates']
    additions = [('', 'i_same_tap'), ('', 'i_skip_tap'), ('', 'i_response_forward'), ('', 'i_saved_valid')]
    all_inputs = inputs + additions
    descriptor = ROOT/'rtl/npu/conv/conv_im2col_descriptor.sv'
    content = descriptor.read_text()
    start = content.index('  assign incoming_word_flags[9]')
    flags = content[start:content.index('  assign incoming_padding_flags[5]', start)]
    start = content.index('  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_word_choice')
    choices = content[start:content.index('  for (genvar candidate = 0; candidate < 9; candidate++) begin : g_padding_choice', start)]
    model = 'module comparison #(parameter int p_word_shift=3)(\n'+',\n'.join('input logic '+w+' '+n for w,n in all_inputs)+''',
output logic actual,expected,equivalent,output logic [9:0] incoming_word_choice);
logic [9:0][5:0] incoming_word_flags;
logic [9:0][1:0] candidate;
wire incoming_window_context=i_next_position_fast;
wire incoming_position_same_tap=i_same_tap;
wire incoming_position_previous_row=i_position_previous_row;
wire incoming_position_forward_tap=i_position_forward_tap;
wire incoming_position_backward_tap=i_position_backward_tap;
wire incoming_window_match=i_same_tap || i_position_previous_row || i_position_forward_tap || i_position_backward_tap;
wire next_position=incoming_window_context && incoming_window_match;
wire o_incoming_next_tile_fast=i_next_tile_fast;
wire o_incoming_skip_tap=i_skip_tap;
wire incoming_q_equal=i_q_equal;
logic [31:0] reference_word_address;
assign reference_word_address=i_word_forward ? {i_addr[31:p_word_shift],{p_word_shift{1'b0}}}:i_word_addr;
'''+flags+choices+'\n'
    for prefix,module in [('actual_','conv_descriptor_addresses'),('reference_','reference_word_addresses')]:
        model += '\n'.join('logic '+w+' '+prefix+n+';' for w,n in outputs)+'\n'
        connections = []
        for _,name in inputs:
            if name=='i_word_forward' and prefix=='reference_':
                continue
            value = 'next_position' if name=='i_next_position_fast' else 'reference_word_address' if name=='i_word_addr' and prefix=='reference_' else name
            connections.append('.'+name+'('+value+')')
        connections += ['.'+name+'('+prefix+name+')' for _,name in outputs]
        if prefix=='actual_':
            connections.append('.o_word_candidates(candidate)')
        model += module+" #(.p_word_shift(p_word_shift),.p_register_descriptor(1'b1),.p_preview_registered(1'b1)) u_"+prefix[:-1]+'('+','.join(connections)+');\n'
    model += 'logic reference_actual;\n'
    for output,prefix in [('reference_actual','actual_'),('expected','reference_')]:
        model += 'assign '+output+' = next_position || i_next_tile_fast || i_skip_tap ?\n'
        model += ' (i_response_forward ? '+prefix+'o_incoming_advanced_word_match[1] : i_saved_valid && '+prefix+'o_incoming_advanced_word_match[0]) :\n'
        model += ' (i_response_forward ? '+prefix+'o_incoming_live_word_equal : i_saved_valid && '+prefix+'o_incoming_word_equal);\n'
    model += '''conv_incoming_word_hit u_hit(.i_select(incoming_word_choice),.i_candidate(candidate),
.i_response_forward,.i_saved_valid,.i_reference(reference_actual),.o_hit(actual));
assign equivalent=actual===expected;
endmodule
'''
    modelpath = out/'comparison.sv'
    modelpath.write_text(model)
    resolver = runpy.run_path(str(ROOT/'scripts/rtl/source_files.py'))
    sources = resolver['with_dependencies']([source,reference,modelpath],ROOT)
    hashes = {str(p.relative_to(ROOT)):digest(p) for p in resolver['input_files'](sources,ROOT) if p.is_relative_to(ROOT)}
    hashes[str(descriptor.relative_to(ROOT))] = digest(descriptor)
    records = []
    declarations = '\n'.join('logic '+w+' '+n+';' for w,n in all_inputs)
    widths = coverage.expanded_widths(out,'localparam int p_word_shift=3;',declarations,[n for _,n in all_inputs])
    bits = sum(widths.values())
    names = ','.join(n for _,n in all_inputs)
    for shift in (2,3,4):
        script,log=out/f'word{shift}.ys',out/f'word{shift}.formal.log'
        script.write_text(shlex.join(['read_slang','--top','comparison','-DSYNTHESIS=1',f'-Gp_word_shift={shift}',*map(str,sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable,str(ROOT/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],
                stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=300)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('候选字完整连接形式检查未完成')
        tb='module tb;\n'+declarations+f'''
logic actual,expected,equivalent;
logic [9:0] incoming_word_choice;
localparam integer p_input_width={bits};
logic [p_input_width-1:0] stimulus;
comparison #(.p_word_shift({shift})) dut(.*);
integer rng=32'h174a9ce3;
integer positive=0,negative=0;
integer selected[10];
function automatic integer random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
initial begin
  foreach(selected[n])selected[n]=0;
  for(integer sample=0;sample<8192;sample++)begin
    for(integer bit_index=0;bit_index<p_input_width;bit_index++)stimulus[bit_index]=1'(random_word());
    case(sample%16)
      0:stimulus='0;
      1:stimulus='1;
      2:stimulus='x;
      3:stimulus='z;
      4,5:stimulus[sample%p_input_width]=1'bx;
      6,7:stimulus[sample%p_input_width]=1'bz;
      default:begin end
    endcase
    {{{names}}}=stimulus;
    if(sample%8==0)begin
      i_word_addr=32'h1000;i_addr=32'h1000;i_row_base_addr=32'h1000;i_window_addr=32'h1000;
      i_tap_step_bytes=0;i_tap_wrap_bytes=0;i_tap_pair_bytes=0;i_row_step_bytes=0;i_row_wrap_bytes=0;
      i_next_row_addr=32'h1000;i_kx0_q=0;i_saved_valid=1;
    end
    if(sample%64==17)begin
      i_next_position_fast=0;i_next_tile_fast=0;i_skip_tap=1;i_kx0_q=0;
    end
    stimulus={{{names}}};
    #1;
    if(equivalent!==1'b1)$fatal(1,"candidate word mismatch sample=%0d actual=%b expected=%b inputs=%h",sample,actual,expected,stimulus);
    if(actual===1'b1)positive++;
    if(actual===1'b0)negative++;
    foreach(selected[n])if(incoming_word_choice[n]===1'b1)selected[n]++;
  end
  foreach(selected[n])if(selected[n]==0)$fatal(1,"candidate source coverage %0d",n);
  if(positive<100 || negative<100)$fatal(1,"word result coverage");
  $display("CANDIDATE_WORD_PASS samples=8192 positive=%0d negative=%0d",positive,negative);
  $finish;
end
endmodule
'''
        tb=tb.replace('initial begin',coverage.declarations('p_input_width')+'initial begin'+coverage.initialize('p_input_width',names),1)
        tb=tb.replace('    #1;',coverage.sample('p_input_width')+'    #1;',1)
        tb=tb.replace('  $display("CANDIDATE_WORD_PASS',coverage.finish('p_input_width')+'  $display("CANDIDATE_WORD_PASS',1)
        bench,binary=out/f'word{shift}.tb.sv',out/f'word{shift}.vvp'
        bench.write_text(tb)
        four=[]
        for synthesis in (False,True):
            sim=out/f'word{shift}.synthesis{int(synthesis)}.log'
            command=['iverilog','-g2012','-s','tb','-o',str(binary)]
            if synthesis:command.append('-DSYNTHESIS=1')
            with sim.open('w') as stream:
                subprocess.run(command+[*map(str,sources),str(bench)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=180)
                subprocess.run(['vvp',str(binary)],stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=900)
            if 'CANDIDATE_WORD_PASS' not in sim.read_text():raise RuntimeError('候选字完整连接四态检查未完成')
            four.append(dict(synthesis=synthesis,comparisons=8192,coverage=coverage.result(sim,widths),log_sha256=digest(sim)))
        records.append(dict(word_bytes=1<<shift,formal_passed=True,formal_log_sha256=digest(log),four_state=four))
        print('CANDIDATE_WORD_PASS '+str(1<<shift),flush=True)
    if any(digest(ROOT/name)!=value for name,value in hashes.items()):raise RuntimeError('验证期间生产源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,formal_properties=len(records),
        four_state_comparisons=len(records)*16384,cases=records,source_sha256=hashes),ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':
    main()
