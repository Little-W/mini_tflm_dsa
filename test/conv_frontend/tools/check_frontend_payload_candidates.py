#!/usr/bin/env python3
"""验证卷积描述符候选、数据字范围和运行字段的完整选择关系。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "test"))
from reference_sources import read_reference_file
DESCRIPTOR = Path('rtl/npu/conv/conv_im2col_descriptor.sv')
STREAM = Path('rtl/npu/conv/conv_im2col_stream.sv')
FRONTEND = Path('rtl/npu/conv/conv_im2col_frontend.sv')
FLAGS = {'i_kx0_q':16,'incoming_window_context':1,'incoming_position_same_tap':1,
         'incoming_position_forward_tap':1,'incoming_position_backward_tap':1,
         'incoming_position_previous_row':1,'o_incoming_next_tile_fast':1,
         'o_incoming_skip_tap':1,'incoming_q_equal':1,'i_incoming_tap_wrap':1}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def section(text, first, last):
    start=text.index(first)
    return text[start:text.index(last,start)]


def statement(text,name):
    match=re.search(r'\bassign\s+'+re.escape(name)+r'\s*=.*?;',text,re.S)
    if match is None:raise ValueError(name)
    return match.group()


def declarations(inputs,direction='input '):
    return [direction+'logic '+(f'[{bits-1}:0] ' if bits>1 else '')+name for name,bits in inputs.items()]


def selector(source):
    choices=section(source,'  // 各候选分别组合完整优先条件','  // 地址、坐标与像素先组成互斥候选')
    return '''
logic incoming_window_match,o_incoming_next_position_fast;
logic [9:0][5:0] incoming_word_flags;
logic [8:0][5:0] incoming_padding_flags;
logic [9:0] incoming_word_choice,prepared_word_select;
logic [8:0] incoming_padding_choice,prepared_padding_select;
assign incoming_window_match=incoming_position_same_tap||incoming_position_forward_tap||
 incoming_position_backward_tap||incoming_position_previous_row;
assign o_incoming_next_position_fast=incoming_window_context&&incoming_window_match;
'''+choices


def filter_assignments(text, allowed):
    pattern=r'(\{[^;{}]+\}|\b[A-Za-z_][A-Za-z_0-9]*(?:\[[^;\]]+\])?)\s*=(?!=)\s*[^;]+;'
    def keep(match):
        lhs=re.sub(r'\s+','',match.group(1))
        return match.group() if lhs in allowed else ';'
    return re.sub(pattern,keep,text)


def proof(inputs,width,body,extra=''):
    return 'module proof(\n'+',\n'.join(declarations(inputs)+[
        'output logic equivalent',f'output logic [{width-1}:0] actual_value,expected_value',
        'output logic [9:0] observed_selection']+([extra] if extra else []))+');\n'+body+'''
assign equivalent=actual_value===expected_value;
assign observed_selection=prepared_word_select;
endmodule
'''


def kernel_reference(source):
    body=section(source,'  always_comb begin\n    incoming_tap=i_tap0;',
                 '\n`ifdef SYNTHESIS\n  assign o_incoming_padding')
    return filter_assignments(body,{'o_incoming_kx','o_incoming_ky','{o_incoming_ky,o_incoming_kx}'})


def kernel_model(current,reference):
    inputs={**FLAGS,'i_ky0_q':16,'window_next_kx':16,'window_next_ky':16}
    body=selector(current)+'''
localparam bit p_register_descriptor=0;
wire [31:0] i_kx0={16'd0,i_kx0_q},i_ky0={16'd0,i_ky0_q};
logic [9:0][63:0] incoming_kernel_values;
logic [63:0] incoming_kernel_selected;
logic [31:0] o_incoming_kx,o_incoming_ky;
for(genvar candidate=0;candidate<10;candidate++)begin:g_values
 logic [31:0] kernel_x_value,kernel_y_value;
'''+statement(current,'kernel_x_value')+'\n'+statement(current,'kernel_y_value')+'\n'+\
        statement(current,'incoming_kernel_values[candidate]')+'\nend\n'+\
        section(current,'  onehot_mux #(.p_choices(10), .p_width(64)) u_incoming_kernel',
                '  assign o_incoming_pixel_select')+'\n'+kernel_reference(current)+'''
assign actual_value={o_incoming_ky,o_incoming_kx};
logic [31:0] expected_kx,expected_ky;
'''+kernel_reference(reference).replace('o_incoming_kx','expected_kx').replace('o_incoming_ky','expected_ky')+'''
assign expected_value={expected_ky,expected_kx};
'''
    return inputs,64,proof(inputs,64,body),False


def word_model(current,descriptor,word_bytes,registered):
    inputs={**FLAGS,'i_state':27,'active_select_commit':1,'o_chunk_reaches_end':1,
            'o_group_end_o_equal':1,'i_coordinate_address_valid':1,'source_address':160,
            'candidate_address':320,'address_update_select':5,'i_rst_n':1}
    block=section(current,'  if (p_saved_word_range) begin : g_saved_word_range',
                  '  // 保存字命中标志与地址共用更新事件')
    body='''import conv_im2col_frontend_pkg::*;
'''+selector(descriptor)+f'''
localparam int p_cache_read_bytes={word_bytes},p_word_shift=$clog2(p_cache_read_bytes);
localparam bit p_register_descriptor={registered},p_saved_word_range=1;
wire [9:0][31:0] i_incoming_address_candidates=candidate_address;
logic [31:0] selected_address;
wire [4:0][31:0] live_address=source_address;
wire [31:0] i_next_row_addr=live_address[1],i_next_tap_addr=live_address[2];
wire [31:0] next_byte_addr=live_address[3],i_channel_addr=live_address[4];
typedef struct packed{{logic [9:0] operation;logic [31:0] address;}} tile_t;
tile_t committing_tile;
logic [p_cache_read_bytes-1:0] word_available_q,expected_q;
always_comb begin
 selected_address='0;
 for(integer source=0;source<10;source++)begin
  if(prepared_word_select[source])selected_address=i_incoming_address_candidates[source];
 end
end
assign committing_tile.operation=prepared_word_select;
assign committing_tile.address=p_register_descriptor?live_address[0]:selected_address;
'''+block+'''
assign actual_value=g_saved_word_range.available_write_value;
assign expected_value=g_saved_word_range.next_available;
always_ff @(posedge i_clk or negedge i_rst_n)begin
 if(!i_rst_n)expected_q<='1;
 else if(|address_update_select)expected_q<=g_saved_word_range.next_available;
end
assign state_equivalent=word_available_q===expected_q;
'''
    return inputs,word_bytes,proof(inputs,word_bytes,body,'input logic i_clk,output logic state_equivalent'),True


def payload_reference(source,renamed):
    first='  // 卷积核列数据按运行阶段预选'
    last='  if (!REGISTER_DESCRIPTOR) begin : g_parallel_descriptor_payload' if renamed else \
        '  // 请求地址、窗口索引和有效位同时寄存'
    text=section(source,first,last)
    if renamed:
        names={'kernel_column_reference','descriptor_payload_context','tap_group_reference','row_group_reference'}
    else:
        names={'kernel_column_payload','descriptor_payload_context','tap_group_payload','row_group_payload'}
    return filter_assignments(text,names)


def payload_model(current,descriptor,registered):
    inputs={**FLAGS,'state':27,'wr_last':1,'chunk_reaches_end':1,'tap_wrap':1,
            'kernel_shape_o_valid':1,'kernel_decode_column':16,'k_decode_value':6,
            'decode_inner':32,'kx':32,'kx0':32,'group_base_addr':32,'next_row_group_base':32,
            'next_tap_addr':32,'candidate_groups':320,'candidate_kernel_x':160,
            'saved_group':32,'saved_kernel_x':16}
    block=section(current,'  if (!REGISTER_DESCRIPTOR) begin : g_parallel_descriptor_payload',
                  '  // 请求地址、窗口索引和有效位同时寄存')
    body='''import conv_im2col_frontend_pkg::*;
'''+selector(descriptor)+f'''
localparam bit REGISTER_DESCRIPTOR={registered};
wire [9:0] incoming_pixel_select=prepared_word_select;
wire [9:0][31:0] incoming_group_candidates=candidate_groups;
wire [9:0][15:0] incoming_kernel_x_candidates=candidate_kernel_x;
logic descriptor_payload_context;
logic [15:0] kernel_column_payload,kernel_column_reference;
logic [31:0] tap_group_payload,row_group_payload,tap_group_reference,row_group_reference;
typedef struct packed{{logic [31:0]group_address;logic [15:0]kernel_x;}} tile_t;
tile_t committing_tile;
always_comb begin
 committing_tile='0;
 for(integer source=0;source<10;source++)begin
  if(prepared_word_select[source])begin
   committing_tile.group_address=incoming_group_candidates[source];
   committing_tile.kernel_x=incoming_kernel_x_candidates[source];
  end
 end
 if(REGISTER_DESCRIPTOR)committing_tile={{saved_group,saved_kernel_x}};
end
'''+payload_reference(current,True)+block+'''
assign actual_value={kernel_column_payload,row_group_payload,tap_group_payload};
assign expected_value={kernel_column_reference,row_group_reference,tap_group_reference};
'''
    return inputs,80,proof(inputs,80,body),False


def directed():
    return '''
 incoming_window_context=0;incoming_position_same_tap=0;
 incoming_position_forward_tap=0;incoming_position_backward_tap=0;incoming_position_previous_row=0;
 o_incoming_next_tile_fast=0;o_incoming_skip_tap=0;incoming_q_equal=0;i_incoming_tap_wrap=0;
 case(candidate_index)
  0:incoming_q_equal=1;
  1:begin end
  2:i_incoming_tap_wrap=1;
  3:begin o_incoming_skip_tap=1;i_kx0_q=0;end
  4:begin o_incoming_skip_tap=1;i_kx0_q=1;end
  5:o_incoming_next_tile_fast=1;
  6:begin incoming_window_context=1;incoming_position_same_tap=1;end
  7:begin incoming_window_context=1;incoming_position_forward_tap=1;end
  8:begin incoming_window_context=1;incoming_position_backward_tap=1;end
  9:begin incoming_window_context=1;incoming_position_previous_row=1;end
 endcase
'''


def bench(inputs,width,sequential,checks):
    bits=sum(inputs.values());padded=(bits+31)//32*32;names=','.join(inputs)
    decl=';\n'.join(declarations(inputs,''))+';'
    extra='logic i_clk=0,state_equivalent;\n' if sequential else ''
    initialize="i_rst_n=0;#1;i_clk=1;#1;i_clk=0;" if sequential else ''
    sample="i_clk=0;#1;i_clk=1;#1;if(state_equivalent!==1'b1)$fatal(1,\"State mismatch sample=%0d\",sample);i_clk=0;" if sequential else '#1;'
    coverage = []
    offset = bits
    for name, count in inputs.items():
        offset -= count
        if name in ('candidate_address', 'candidate_groups', 'candidate_kernel_x'):
            item_width = 16 if name == 'candidate_kernel_x' else 32
            coverage.append(f'  if(sample<2*{bits} && sample/2>={offset} && sample/2<{offset+count})begin candidate_index=(sample/2-{offset})/{item_width};' + ('active_select_commit=1;' if name == 'candidate_address' else "state=27'h1;wr_last=0;") + 'end')
    coverage_text='\n'.join(coverage)
    return f'''module tb;
{decl}
{extra}logic equivalent;
logic [{width-1}:0]actual_value,expected_value;
logic [9:0]observed_selection,seen_selection='0;
logic [{padded-1}:0]pattern;
logic [{bits-1}:0]applied,seen_x='0,seen_z='0;
integer candidate_index;
proof dut(.*);
initial begin
 {{{names}}}='0;
 {initialize}
 for(integer sample=0;sample<{checks};sample++)begin
  for(integer word_index=0;word_index<{padded//32};word_index++)pattern[32*word_index+:32]=$urandom;
  {{{names}}}=pattern;
  candidate_index=sample%10;
{coverage_text}
{directed()}
  applied={{{names}}};
  if(sample<2*{bits})applied[sample/2]=(sample%2)?1'bz:1'bx;
  {{{names}}}=applied;
  for(integer b=0;b<{bits};b++)begin
   if(applied[b]===1'bx)seen_x[b]=1'b1;
   if(applied[b]===1'bz)seen_z[b]=1'b1;
  end
  {sample}
  if(equivalent!==1'b1)$fatal(1,"Candidate mismatch sample=%0d actual=%h expected=%h input=%h",sample,actual_value,expected_value,applied);
  if((^observed_selection)!==1'bx)seen_selection|=observed_selection;
 end
 if(seen_x!=='1||seen_z!=='1||seen_selection!==10'h3ff)$fatal(1,"Incomplete X/Z or candidate coverage");
 $display("FRONTEND_PAYLOAD_FOUR_STATE_PASS checks={checks} bits={bits} candidates=%h",seen_selection);
 $finish;
end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--reference-ref',required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cases',nargs='+')
    parser.add_argument('--iverilog',default=shutil.which('iverilog') or 'iverilog')
    parser.add_argument('--vvp',default=shutil.which('vvp') or 'vvp')
    args=parser.parse_args();root,out=args.source_root.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    utilities=runpy.run_path(str(Path(__file__).with_name('check_frontend_range_comparisons.py')))
    paths=[DESCRIPTOR,STREAM,FRONTEND,Path('rtl/common/onehot_mux.sv'),Path('rtl/npu/conv/conv_im2col_frontend_pkg.sv')]
    current={p:(root/p).read_text() for p in paths}
    previous={p:read_reference_file(root, args.reference_ref, str(p), text=True) for p in (DESCRIPTOR,STREAM,FRONTEND)}
    hashes={str(root/p):digest(root/p) for p in paths}
    for p in [Path(__file__).resolve(),Path(__file__).with_name('check_frontend_range_comparisons.py')]:hashes[str(p)]=digest(p)
    for token in ['assign ky0 = 32\'(ky0_q);','assign kx0 = 32\'(kx0_q);',
                  '.i_incoming_address_candidates(incoming_address_candidates)',
                  '.o_incoming_group_candidates(incoming_group_candidates)',
                  '.o_incoming_kernel_x_candidates(incoming_kernel_x_candidates)']:
        if token not in current[FRONTEND]:raise ValueError('Missing production relation: '+token)
    for name in ['next_available[byte_index]','source_low[0]']:
        if statement(current[STREAM],name)!=statement(previous[STREAM],name):raise ValueError('Word range reference changed')
    normalized=payload_reference(previous[FRONTEND],False).replace('kernel_column_payload','kernel_column_reference').replace('tap_group_payload','tap_group_reference').replace('row_group_payload','row_group_reference')
    if normalized!=payload_reference(current[FRONTEND],True):raise ValueError('Runtime payload reference changed')
    helper=out/'descriptor_qualify.sv';helper.write_text(utilities['module'](current[DESCRIPTOR],'conv_descriptor_qualify'))
    support=[root/'rtl/common/onehot_mux.sv',root/'rtl/npu/conv/conv_im2col_frontend_pkg.sv',helper]
    selector_body=selector(current[DESCRIPTOR])+'''
assign actual_value=prepared_word_select!=0&&((prepared_word_select&(prepared_word_select-10'd1))==0);
assign expected_value=1'b1;
'''
    specs=[('selection_domain',(FLAGS,1,proof(FLAGS,1,selector_body),False)),
           ('kernel_position',kernel_model(current[DESCRIPTOR],previous[DESCRIPTOR]))]
    specs += [(f'word_bytes{word_bytes}_registered{registered}',word_model(current[STREAM],current[DESCRIPTOR],word_bytes,registered))
              for word_bytes in (2,3,4,8,16) for registered in (0,1)]
    specs += [(f'payload_registered{registered}',payload_model(current[FRONTEND],current[DESCRIPTOR],registered)) for registered in (0,1)]
    results=[];mapping={}
    for name,(inputs,width,text,sequential) in specs:
        if args.cases and name not in args.cases:continue
        model=out/(name+'_model.sv');model.write_text(text.replace('always_comb','always @*'))
        ys,log,tb,binary,build,simulation=[out/(name+suffix) for suffix in ('.ys','.formal.log','.tb.sv','.vvp','.build.log','.four_state.log')]
        commands='sat -verify -prove equivalent 1 -show-inputs -show-outputs\n'
        if sequential:
            commands='sat -seq 1 -verify -prove equivalent 1 -show-inputs -show-outputs\n'+\
                'sat -seq 2 -set-at 1 i_rst_n 0 -prove-skip 1 -prove state_equivalent 1 -verify\n'+\
                'sat -seq 1 -tempinduct-inductonly -maxsteps 1 -prove state_equivalent 1 -verify\n'
        ys.write_text('read_slang -DSYNTHESIS --top proof '+shlex.join(map(str,support+[model]))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
            'prep -top proof -flatten\nasync2sync\nopt\ncheck -assert\n'+commands)
        with log.open('w') as f:subprocess.run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=180)
        if 'SUCCESS!' not in log.read_text():raise RuntimeError(str(log))
        checks=max(2048,256*((2*sum(inputs.values())+255)//256)+256)
        tb.write_text(bench(inputs,width,sequential,checks))
        with build.open('w') as f:subprocess.run([args.iverilog,'-g2012','-s','tb','-o',str(binary),*map(str,support+[model,tb])],stdout=f,stderr=subprocess.STDOUT,check=True)
        with simulation.open('w') as f:subprocess.run([args.vvp,str(binary)],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=600)
        if 'FRONTEND_PAYLOAD_FOUR_STATE_PASS' not in simulation.read_text():raise RuntimeError(str(simulation))
        binary.unlink()
        results.append(dict(name=name,formal_properties=3 if sequential else 1,formal_passed=True,four_state_checks=checks,
            input_bits=sum(inputs.values()),all_input_bits_x_z=True,all_descriptor_candidates=True,
            model_sha256=digest(model),formal_log_sha256=digest(log),simulation_log_sha256=digest(simulation)))
        if name in ('kernel_position','word_bytes8_registered0','payload_registered0'):
            for kind in ('actual','expected'):
                wrapper=out/(name+'_'+kind+'_mapping.sv');content=utilities['mapping_wrapper'](inputs,width,kind)
                content=content.replace('logic unused_equivalent;','logic unused_equivalent;\nwire [9:0]unused_selection;')
                content=content.replace('.equivalent(unused_equivalent)', '.equivalent(unused_equivalent),.observed_selection(unused_selection)'+(', .i_clk(clk), .state_equivalent()' if sequential else ''))
                wrapper.write_text(content)
                mapping[name+'_'+kind]=dict(top='comparison_mapping',options=['-D','SYNTHESIS=1'],sources=list(map(str,support+[model,wrapper])),configuration='Registered complete descriptor payload selection')
        print('FRONTEND_PAYLOAD_PASS',name,flush=True)
    if hashes!={p:digest(p) for p in hashes}:raise RuntimeError('检查期间源码发生变化')
    (out/'mapping_cases.json').write_text(json.dumps(mapping,indent=2)+'\n')
    (out/'summary.json').write_text(json.dumps(dict(passed=True,source_sha256=hashes,sources_unchanged=True,
        reference_ref=args.reference_ref,reference_sha256={str(p):hashlib.sha256(s.encode()).hexdigest() for p,s in previous.items()},
        formal_properties=sum(x['formal_properties'] for x in results),four_state_checks=sum(x['four_state_checks'] for x in results),
        production_selection_domain='Exactly one of ten descriptor candidates for every binary input combination.',
        field_relations='Kernel input aliases and frontend candidate connections are checked in production source.',cases=results),indent=2)+'\n')


if __name__=='__main__':
    main()
