#!/usr/bin/env python3
"""验证描述符比较归并、接收资格及候选数据字命中的完整结果。"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shlex
import subprocess
import sys

import four_state_coverage as coverage

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cases():
    for width in (1, 2, 3, 4, 5, 16, 17, 28, 29, 32, 33, 64):
        yield (f'match{width}', [('i_a', width, f'[{width-1}:0]'), ('i_b', width, f'[{width-1}:0]')],
            f'''conv_descriptor_match #(.p_width({width}),.p_preserve_groups(1'b1),.p_reduce_group_width(6)) u_match(
.i_a,.i_b,.o_equal(actual));
assign expected=i_a==i_b;''',
            "if(sample%8==0)i_b=i_a;\n    if(sample%8==1)i_b=~i_a;")
    for width in (1, 2, 5, 16, 28, 29, 32, 35):
        for step in range(4):
            yield (f'saved_match{width}_step{step}', [('i_a',width,f'[{width-1}:0]'),
                ('i_saved',width,f'[{width-1}:0]'),('i_forward',1,'')],
                f'''logic [{width-1}:0] target;
assign target=i_forward ? i_a : i_saved;
conv_saved_word_step_match #(.p_width({width}),.p_step({step})) u_saved(.i_a,.i_saved,.i_forward,.o_equal(actual));
add_equal #(.p_width({width})) u_reference(.i_a,.i_b({width}'({step})),.i_target(target),.i_carry_in(1'b0),.o_equal(expected));''',
                f"if(sample%8==0)i_saved=i_a+{width}'({step});\n    if(sample%8==1)i_saved=~i_a;")
    for width in (17, 32, 35):
        yield (f'coordinate_limit{width}', [('i_coordinate',width,f'[{width-1}:0]'),('i_limit',16,'[15:0]')],
            f"""conv_coordinate_limit #(.p_width({width})) u_limit(.i_coordinate,.i_limit,.o_valid(actual));
assign expected=!(|i_coordinate[{width-1}:16]) && i_coordinate[15:0]<i_limit;""",
            "if(sample%8==0)i_coordinate=0;\n    if(sample%8==1)i_coordinate="+str(width)+"'(i_limit);")
    for width in (4, 5, 6):
        yield (f'borrow{width}', [('i_a',width,f'[{width-1}:0]'),('i_b',width,f'[{width-1}:0]')],
            f"""logic [{width}:0] difference,reference_difference;
borrow_select_subtract #(.p_width({width})) u_subtract(.i_a,.i_b,.o_difference(difference));
assign reference_difference={{1'b0,i_a}}-{{1'b0,i_b}};
assign actual=difference===reference_difference;
assign expected=1'b1;""", "")
    for register in (0, 1):
        names = ['i_idle_context', 'i_output_context', 'i_early_output', 'i_chunk_end',
                 'i_prepared_valid', 'i_fast', 'i_configure']
        yield (f'admission{register}', [(name, 1, '') for name in names]+[('i_commit_context',2,'[1:0]')],
            f'''conv_descriptor_admission #(.p_register_descriptor({register})) u_admission(
'''+','.join('.'+name for name in names)+''',.i_commit_context,.o_ready(actual));
assign expected=(i_idle_context || (i_output_context && i_chunk_end) ||
    (i_early_output && i_chunk_end && i_fast)) && !i_configure &&
    (!'''+str(register)+''' || !i_prepared_valid || ((i_commit_context[0] || i_commit_context[1] && i_chunk_end) && i_fast));''', '')
    text = (ROOT / 'rtl/npu/conv/conv_im2col_descriptor.sv').read_text()
    start = text.index('  assign incoming_word_flags[9]')
    flags = text[start:text.index('  assign incoming_padding_flags[5]', start)]
    start = text.index('  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_word_choice')
    choices = text[start:text.index('  for (genvar candidate = 0; candidate < 9; candidate++) begin : g_padding_choice', start)]
    names = ['incoming_window_context', 'incoming_position_same_tap', 'incoming_position_previous_row',
             'incoming_position_forward_tap', 'incoming_position_backward_tap', 'o_incoming_next_tile_fast',
             'o_incoming_skip_tap', 'incoming_q_equal', 'i_incoming_tap_wrap']
    ports = [(name, 1, '') for name in names] + [('i_kx0_q', 16, '[15:0]'),
        ('candidate', 20, '[9:0][1:0]'), ('response_forward', 1, ''), ('saved_valid', 1, '')]
    body = '''logic [9:0][5:0] incoming_word_flags;
logic [9:0] incoming_word_choice;
logic [1:0] ordinary_match, advanced_match, window_match;
wire incoming_window_match=incoming_position_same_tap || incoming_position_previous_row ||
    incoming_position_forward_tap || incoming_position_backward_tap;
wire next_position=incoming_window_context && incoming_window_match;
''' + flags + choices + '''
assign ordinary_match=incoming_q_equal ? candidate[0] :
    (i_incoming_tap_wrap ? candidate[2] : candidate[1]);
assign window_match=incoming_position_previous_row ? candidate[9] :
    incoming_position_forward_tap ? candidate[7] : incoming_position_backward_tap ? candidate[8] : candidate[6];
assign advanced_match=next_position ? window_match : o_incoming_next_tile_fast ? candidate[5] :
    i_kx0_q!=0 ? candidate[4] : candidate[3];
assign expected=next_position || o_incoming_next_tile_fast || o_incoming_skip_tap ?
    (response_forward ? advanced_match[1] : saved_valid && advanced_match[0]) :
    (response_forward ? ordinary_match[1] : saved_valid && ordinary_match[0]);
conv_incoming_word_hit u_hit(.i_select(incoming_word_choice),.i_candidate(candidate),
    .i_response_forward(response_forward),.i_saved_valid(saved_valid),.i_reference(expected),.o_hit(actual));
'''
    yield ('word_choice', ports, body, "if(sample%8==0)i_kx0_q=0;")
    start = text.index('  assign incoming_word_flags[9]')
    padding_flags = text[start:text.index('  for (genvar candidate = 0; candidate < 10;', start)]
    start = text.index('  for (genvar candidate = 0; candidate < 9; candidate++) begin : g_padding_choice')
    padding_choice = text[start:text.index('  always_comb begin', start)]
    start = text.index('  (* keep_hierarchy = "yes" *) onehot_mux #(.p_choices(9)')
    padding_mux = text[start:text.index('  );', start)+5]
    start = text.index('  always_comb begin\n    o_incoming_padding = incoming_padding_reference;')
    padding_output = text[start:text.index('`else', start)].replace('o_incoming_padding','actual')
    padding_ports = [(name,1,'') for name in names] + [('i_kx0_q',16,'[15:0]'),
        ('prepared_padding_value',9,'[8:0]')]
    padding_body = """logic [9:0][5:0] incoming_word_flags;
logic [8:0][5:0] incoming_padding_flags;
logic [8:0] incoming_padding_choice,prepared_padding_select;
logic incoming_padding_selected,incoming_padding_reference;
wire incoming_window_match=incoming_position_same_tap || incoming_position_previous_row ||
    incoming_position_forward_tap || incoming_position_backward_tap;
wire next_position=incoming_window_context && incoming_window_match;
""" + padding_flags + padding_choice + padding_mux + """
assign prepared_padding_select=incoming_padding_choice;
always_comb begin
  incoming_padding_reference=prepared_padding_value[0];
  if(next_position)begin
    if(incoming_position_same_tap)incoming_padding_reference=prepared_padding_value[5];
    else if(incoming_position_previous_row)incoming_padding_reference=prepared_padding_value[8];
    else if(incoming_position_forward_tap)incoming_padding_reference=prepared_padding_value[6];
    else incoming_padding_reference=prepared_padding_value[7];
  end else if(o_incoming_next_tile_fast)incoming_padding_reference=prepared_padding_value[4];
  else if(o_incoming_skip_tap)incoming_padding_reference=prepared_padding_value[3];
  else if(!incoming_q_equal)incoming_padding_reference=i_incoming_tap_wrap ?
      prepared_padding_value[2] : prepared_padding_value[1];
end
assign expected=incoming_padding_reference;
""" + padding_output
    yield ('padding_choice',padding_ports,padding_body,'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args().out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    resolver = runpy.run_path(str(ROOT / 'scripts/rtl/source_files.py'))
    records, hashes = [], {}
    for name, ports, body, directed in cases():
        model = out / (name+'.sv')
        model.write_text('module comparison(\n'+',\n'.join('input logic '+width+' '+port for port, _, width in ports)+
            ',\noutput logic actual,expected,equivalent);\n'+body+'\nassign equivalent=actual===expected;\nendmodule\n')
        sources = resolver['with_dependencies']([model], ROOT)
        for p in resolver['input_files'](sources, ROOT):
            if p.is_relative_to(ROOT):
                hashes[str(p.relative_to(ROOT))] = digest(p)
        script, log = out/(name+'.ys'), out/(name+'.formal.log')
        script.write_text(shlex.join(['read_slang', '--top', 'comparison', '-DSYNTHESIS=1', *map(str, sources)])+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top comparison -flatten\nsat -verify -prove equivalent 1\n')
        with log.open('w') as stream:
            subprocess.run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)],
                stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError('描述符选择形式检查未完成')
        width = sum(bits for _, bits, _ in ports)
        names = ','.join(port for port, _, _ in ports)
        declarations = '\n'.join('logic '+bits+' '+port+';' for port, _, bits in ports)
        tb = 'module tb;\n'+declarations+f'''
logic actual,expected,equivalent;
localparam integer p_input_width={width};
logic [p_input_width-1:0] stimulus;
comparison dut(.*);
integer rng=32'h51c7f392;
integer positive=0,negative=0;
function automatic integer random_word;
  rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);return rng;
endfunction
initial begin
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
    {directed}
    stimulus={{{names}}};
    #1;
    if(equivalent!==1'b1)$fatal(1,"selection mismatch sample=%0d expected=%b actual=%b stimulus=%h",sample,expected,actual,stimulus);
    if(actual===1'b1)positive++;
    if(actual===1'b0)negative++;
  end
  if(positive<10 || (negative<10 && "{name}"!="borrow4" && "{name}"!="borrow5" && "{name}"!="borrow6"))$fatal(1,"selection result coverage");
  $display("DESCRIPTOR_SELECTION_PASS samples=8192 positive=%0d negative=%0d",positive,negative);
  $finish;
end
endmodule
'''
        tb = tb.replace('initial begin', coverage.declarations('p_input_width')+'initial begin'+
            coverage.initialize('p_input_width', names), 1)
        tb = tb.replace('    #1;', coverage.sample('p_input_width')+'    #1;', 1)
        tb = tb.replace('  $display("DESCRIPTOR_SELECTION_PASS', coverage.finish('p_input_width')+
            '  $display("DESCRIPTOR_SELECTION_PASS', 1)
        bench, binary = out/(name+'.tb.sv'), out/(name+'.vvp')
        bench.write_text(tb)
        simulation = out/(name+'.four_state.log')
        with simulation.open('w') as stream:
            subprocess.run(['iverilog', '-g2012', '-DSYNTHESIS=1', '-s', 'tb', '-o', str(binary),
                *map(str, sources), str(bench)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=120)
            subprocess.run(['vvp', str(binary)], stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
        if 'DESCRIPTOR_SELECTION_PASS' not in simulation.read_text():
            raise RuntimeError('描述符选择四态检查未完成')
        records.append(dict(name=name, formal_passed=True, formal_log_sha256=digest(log),
            four_state_comparisons=8192, coverage=coverage.result(simulation, {p:b for p,b,_ in ports}),
            four_state_log_sha256=digest(simulation)))
        print('DESCRIPTOR_SELECTION_PASS '+name, flush=True)
    hashes['rtl/npu/conv/conv_im2col_descriptor.sv'] = digest(ROOT/'rtl/npu/conv/conv_im2col_descriptor.sv')
    if any(digest(ROOT/name)!=value for name,value in hashes.items()):
        raise RuntimeError('验证期间生产源码发生变化')
    (out/'summary.json').write_text(json.dumps(dict(passed=True, cases=records, source_sha256=hashes,
        formal_properties=len(records), four_state_comparisons=8192*len(records)), ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
