#!/usr/bin/env python3
"""检查读取状态资格与状态字的同时更新及完整地址来源选择。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_reference(revision, path):
    return subprocess.check_output(['git','show',revision+':'+path],cwd=ROOT,text=True)


def updates(text):
    values=re.findall(r'\{([\w,]+,state)\}\s*<=\s*vector_engine_control_pkg::state_control_value\(([^;]+)\);',text)
    if not values or len({target for target,_ in values})!=1:
        raise RuntimeError('状态更新字段不一致')
    if re.search(r'(?<!\w)state\s*<=',text):
        raise RuntimeError('状态更新未使用完整控制字')
    return values[0][0].split(','),[re.sub(r'\s+','',value) for _,value in values]


def selection(text):
    if 'vector_read_address_select u_read_select' in text:
        begin=text.index("  always_comb begin\n    read_select_i_load_base = 32'd0;")
        declarations='''  logic [31:0] read_select_i_load_base, read_select_i_load_offset;
  logic read_select_i_lut_read, read_select_i_pool_read;
'''
    else:
        begin=text.index('  always_comb begin\n    read_address_base = 32\'d0;')
        declarations=''
    end=text.index('  vector_read_address_add u_read_address',begin)
    return declarations+text[begin:end].replace('vector_engine_control_pkg::','')


def run(command, log):
    with log.open('w') as stream:
        subprocess.run([str(value) for value in command],cwd=ROOT,stdout=stream,
                       stderr=subprocess.STDOUT,check=True,timeout=300)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-revision',default='7ddc0d8d')
    parser.add_argument('--source-root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    relative=['rtl/npu/conv/'+name+'.sv' for name in
              ('vector_engine_control_pkg','vector_engine_control','vector_engine_address')]
    original={name:read_reference(args.reference_revision,name) for name in relative}
    source_root=args.source_root.resolve()
    current={name:(source_root/name).read_text() for name in relative}
    hashes={name:digest(source_root/name) for name in relative}
    selector=''
    if 'vector_read_address_select u_read_select' in current[relative[2]]:
        helper='rtl/npu/conv/vector_read_address_select.sv'
        selector=(source_root/helper).read_text()
        hashes[helper]=digest(source_root/helper)
    old_fields,old_updates=updates(original[relative[1]])
    new_fields,new_updates=updates(current[relative[1]])
    if old_updates!=new_updates or new_fields!=['state_soft_lut_read','state_pool_read']+old_fields:
        raise RuntimeError('状态转移或已有控制字字段发生变化')
    original_load_updates=re.findall(r'(?<!\w)load_kind\s*<=([^;]+);',original[relative[1]])
    selected_load_updates=re.findall(r'\{load_read_select,load_kind\}\s*<=vector_engine_control_pkg::load_control_value\(([^;]+)\);',current[relative[1]])
    if original_load_updates!=selected_load_updates or len(selected_load_updates)!=9:
        raise RuntimeError('读取类型的更新条件或右侧表达式发生变化')
    load_function=re.search(r'function automatic logic \[8:0\] load_control_value.*?endfunction',current[relative[0]],re.S)[0]
    load_function=load_function.replace('input load_t next_load','input logic [2:0] next_load')
    enum=re.search(r'typedef enum logic \[5:0\].*?state_t;',current[relative[0]],re.S)[0]
    load_enum=re.search(r'typedef enum logic \[2:0\].*?load_t;',current[relative[0]],re.S)[0]
    functions=[]
    for label,text in (('original',original[relative[0]]),('selected',current[relative[0]])):
        function=re.search(r'function automatic logic .*?state_control_value\(.*?endfunction',text,re.S)[0]
        function=function.replace('state_control_value',label+'_control_value')
        function=function.replace('$bits(state_t)','6').replace('input state_t next_state','input logic [5:0] next_state')
        functions.append(function)
    old_width=len(old_fields)+5
    new_width=len(new_fields)+5
    control=args.out/'control_word.sv'
    control.write_text(f'''module control_word(input wire clk, rst_n, load,
    input wire [5:0] next_state, output wire comb_equal, saved_equal,
    output wire [{old_width-1}:0] original_word,
    output wire [{new_width-1}:0] selected_word,
    output reg [{old_width-1}:0] original_saved,
    output reg [{new_width-1}:0] selected_saved);
{enum}
{chr(10).join(functions)}
wire [1:0] expected = {{(next_state==SOFT_LUT_REQ || next_state==SOFT_LUT_WAIT),
                       (next_state==POOL_LOAD_REQ || next_state==POOL_LOAD_WAIT)}};
wire [1:0] expected_saved = {{(selected_saved[5:0]==SOFT_LUT_REQ || selected_saved[5:0]==SOFT_LUT_WAIT),
                             (selected_saved[5:0]==POOL_LOAD_REQ || selected_saved[5:0]==POOL_LOAD_WAIT)}};
assign original_word=original_control_value(next_state);
assign selected_word=selected_control_value(next_state);
assign comb_equal=(selected_word[{old_width-1}:0]==original_word) &&
                  (selected_word[{new_width-1}:{old_width}]==expected);
always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        original_saved<=original_control_value(IDLE);
        selected_saved<=selected_control_value(IDLE);
    end else if(load) begin
        original_saved<=original_word;
        selected_saved<=selected_word;
    end
end
assign saved_equal=(selected_saved[{old_width-1}:0]==original_saved) &&
                   (selected_saved[{new_width-1}:{old_width}]==expected_saved);
endmodule
''')
    source=args.out/'source_choice.sv'
    sections=[]
    for label,text in (('original',original[relative[2]]),('selected',current[relative[2]])):
        block=selection(text)
        sections.append(f'''module {label}_choice(input wire [5:0] state,
    input wire [2:0] load_kind,
    input wire [31:0] input_base, rhs_base, bias_base, multiplier_base, shift_base,
    input wire vector_s16, input wire [15:0] channel_base,
    input wire [31:0] vector_offset, pool_byte_offset,
    input wire [7:0] soft_lut_index_q,
    output reg [31:0] read_address_base, read_address_offset,
    output reg [15:0] read_address_channel);
{enum}
{load_enum}
{load_function}
wire [8:0] selected_load_word=load_control_value(load_kind);
wire [5:0] i_load_read_select=selected_load_word[8:3];
localparam p_registered_read_phase=1'b1;
wire i_state_soft_lut_read=(state==SOFT_LUT_REQ || state==SOFT_LUT_WAIT);
wire i_state_pool_read=(state==POOL_LOAD_REQ || state==POOL_LOAD_WAIT);
'''+re.sub(r'\bc\.(input_base|rhs_base|bias_base|multiplier_base|shift_base|vector_s16)\b',r'\1',block)+'endmodule\n')
    inputs=['input_base','rhs_base','bias_base','multiplier_base','shift_base','vector_offset','pool_byte_offset']
    names=['state','load_kind',*inputs,'vector_s16','channel_base','soft_lut_index_q']
    common=', '.join('.'+name+'('+name+')' for name in names)
    source.write_text('\n'.join(sections)+selector+'''module source_choice(input wire [5:0] state,
    input wire [2:0] load_kind, input wire [31:0] '''+', '.join(inputs)+''',
    input wire vector_s16, input wire [15:0] channel_base,
    input wire [7:0] soft_lut_index_q,
    output wire [79:0] original_result, selected_result, output wire equal);
original_choice u_original('''+common+''',.read_address_base(original_result[79:48]),
    .read_address_offset(original_result[47:16]),.read_address_channel(original_result[15:0]));
selected_choice u_selected('''+common+''',.read_address_base(selected_result[79:48]),
    .read_address_offset(selected_result[47:16]),.read_address_channel(selected_result[15:0]));
assign equal=original_result==selected_result;
endmodule
''')
    load_control=args.out/'load_word.sv'
    load_control.write_text(f'''module load_word(input wire clk, rst_n, load,
    input wire [2:0] load_kind, output wire comb_equal, saved_equal,
    output wire [8:0] selected_word, output reg [8:0] selected_saved);
{load_enum}
{load_function}
function automatic [5:0] expected_select(input [2:0] kind);
    expected_select=6'b000000;
    for(integer index=0;index<6;index=index+1)
        if(kind===3'(index)) expected_select[index]=1'b1;
endfunction
assign selected_word=load_control_value(load_kind);
assign comb_equal=(selected_word=={{expected_select(load_kind),load_kind}});
always @(posedge clk or negedge rst_n) begin
    if(!rst_n) selected_saved<=load_control_value(LD_WEIGHT);
    else if(load) selected_saved<=selected_word;
end
assign saved_equal=selected_saved[8:3]==expected_select(selected_saved[2:0]);
endmodule
''')
    jobs=[('source_choice',source,'source_choice','sat -verify -prove equal 1 -show-inputs -show-outputs'),
          ('control_word',control,'control_word','delete w:original_saved w:selected_saved w:saved_equal w:expected_saved; opt_clean; sat -verify -prove comb_equal 1'),
          ('control_sequence',control,'control_word','async2sync; sat -verify -seq 3 -set-at 1 rst_n 0 -prove-skip 1 -prove saved_equal 1'),
          ('control_induction',control,'control_word','async2sync; sat -verify -seq 1 -tempinduct-inductonly -maxsteps 1 -prove saved_equal 1'),
          ('load_word',load_control,'load_word','delete w:selected_saved w:saved_equal; opt_clean; sat -verify -prove comb_equal 1'),
          ('load_sequence',load_control,'load_word','async2sync; sat -verify -seq 3 -set-at 1 rst_n 0 -prove-skip 1 -prove saved_equal 1'),
          ('load_induction',load_control,'load_word','async2sync; sat -verify -seq 1 -tempinduct-inductonly -maxsteps 1 -prove saved_equal 1')]
    for label,path,top,proof in jobs:
        script=args.out/(label+'.ys')
        script.write_text('read_verilog -sv '+shlex.quote(str(path))+
            '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy'+
            '\nprep -top '+top+' -flatten\ncheck -assert\n'+proof+'\n')
        run([sys.executable,ROOT/'scripts/fpga/open_fpga_synth.py','--worker',script],script.with_suffix('.log'))
    bench=args.out/'four_state.sv'
    bench.write_text(f'''module tb;
reg clk=0, rst_n=1, load=0;
reg [5:0] next_state, state;
reg [2:0] load_kind;
reg [31:0] {', '.join(inputs)};
reg vector_s16;
reg [15:0] channel_base;
reg [7:0] soft_lut_index_q;
wire [{old_width-1}:0] original_word, original_saved;
wire [{new_width-1}:0] selected_word, selected_saved;
wire [79:0] original_result, selected_result;
wire comb_equal, saved_equal, equal;
wire [8:0] selected_load_word, selected_load_saved;
integer encoded, checks=0;
reg [31:0] random_state=32'h892b41e7;
control_word u_word(.*);
source_choice u_choice(.*);
load_word u_load(.clk(clk),.rst_n(rst_n),.load(load),.load_kind(load_kind),
    .comb_equal(),.saved_equal(),.selected_word(selected_load_word),
    .selected_saved(selected_load_saved));
task verify; begin
    #1;
    if (selected_word[{old_width-1}:0] !== original_word ||
        selected_word[{new_width-1}:{old_width}] !== u_word.expected)
        $fatal(1,"control word differs");
    if (selected_load_word !== {{u_load.expected_select(load_kind),load_kind}})
        $fatal(1,"load word differs");
    if (selected_result !== original_result) $fatal(1,"source choice differs");
    checks=checks+1;
end endtask
initial begin
    rst_n=0; #1; clk=1; #1; clk=0; rst_n=1;
    for(integer sample=0;sample<262144;sample=sample+1) begin
        random_state=random_state^(random_state<<13);
        random_state=random_state^(random_state>>17);
        random_state=random_state^(random_state<<5);
        encoded=sample%4096;
        for(integer bit_index=0;bit_index<6;bit_index=bit_index+1) begin
            case(encoded%4)
                0:next_state[bit_index]=1'b0;
                1:next_state[bit_index]=1'b1;
                2:next_state[bit_index]=1'bx;
                3:next_state[bit_index]=1'bz;
            endcase
            encoded=encoded/4;
        end
        state=next_state; encoded=sample/4096;
        for(integer bit_index=0;bit_index<3;bit_index=bit_index+1) begin
            case(encoded%4)
                0:load_kind[bit_index]=1'b0;
                1:load_kind[bit_index]=1'b1;
                2:load_kind[bit_index]=1'bx;
                3:load_kind[bit_index]=1'bz;
            endcase
            encoded=encoded/4;
        end
        input_base=random_state; rhs_base=~random_state;
        bias_base=random_state^32'ha531e27d; multiplier_base=random_state+32'd17;
        shift_base=random_state-32'd29; vector_offset=random_state^32'h927b1683;
        pool_byte_offset=~vector_offset; vector_s16=random_state[5];
        channel_base=random_state[15:0]; soft_lut_index_q=random_state[31:24];
        load=random_state[7]; verify();
        clk=1; #1;
        if(selected_saved[{old_width-1}:0]!==original_saved ||
           selected_saved[{new_width-1}:{old_width}]!==u_word.expected_saved)
           $fatal(1,"saved word differs");
        if(selected_load_saved[8:3]!==u_load.expected_select(selected_load_saved[2:0]))
           $fatal(1,"saved load word differs");
        clk=0; #1;
    end
    $display("FOUR_STATE_PASS checks=%0d",checks); $finish;
end
endmodule
''')
    executable=args.out/'four_state.vvp'
    run(['iverilog','-g2012','-s','tb','-o',executable,control,load_control,source,bench],args.out/'iverilog.log')
    run(['vvp',executable],args.out/'four_state.log')
    if 'FOUR_STATE_PASS checks=262144' not in (args.out/'four_state.log').read_text():
        raise RuntimeError('四态比较未完成')
    if hashes!={name:digest(source_root/name) for name in hashes}:
        raise RuntimeError('验证期间源码发生变化')
    summary=dict(passed=True,reference_revision=args.reference_revision,sources_sha256=hashes,
                 state_updates=len(new_updates),load_updates=len(selected_load_updates),
                 formal_properties=len(jobs),four_state_cases=262144,
                 added_pipeline_cycles=0,tests_sha256=digest(Path(__file__)))
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
