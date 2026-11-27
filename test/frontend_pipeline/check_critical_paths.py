#!/usr/bin/env python3
"""验证前端完整定宽坐标、地址和预取运算，并生成组合运算的综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import read_module, declarations, dependencies
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'test'))
from four_state_inputs import coverage_declarations, coverage_tasks, parse_coverage


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, log, timeout=240):
    with log.open('w') as output:
        result = subprocess.run(command, cwd=ROOT, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(log))


def section(text, first, last):
    start = text.index(first)
    return text[start:text.index(last, start)]


def prepare_mapping(out, helpers, arithmetic):
    wrappers = out/'registered_arithmetic.sv'
    blocks = []
    cases = {}
    for kind, input_width, output_width in (('coordinate', 86, 36), ('movement', 320, 160),
                                            ('row', 161, 2), ('horizontal', 102, 35)):
        for mode in ('actual', 'mathematical'):
            top = f'{kind}_{mode}_registered'
            text = f'''module {top}(input logic clk,input logic [{input_width-1}:0] inputs,
 output logic [{output_width-1}:0] result);
 logic [{input_width-1}:0] inputs_q;
 logic [{output_width-1}:0] result_next;
 always_ff @(posedge clk)begin inputs_q<=inputs;result<=result_next;end
'''
            if kind == 'coordinate':
                module = 'conv_coordinate_step' if mode == 'actual' else 'coordinate_mathematical'
                text += f''' {module} u_value(.i_base(inputs_q[85:51]),.i_delta(inputs_q[50:16]),
   .i_limit(inputs_q[15:0]),.o_sum(result_next[35:1]),.o_valid(result_next[0]));
'''
            elif kind == 'movement':
                if mode == 'actual':
                    text += ''' movement_actual u_value(.movement_i_a(inputs_q[159:0]),
   .movement_i_b(inputs_q[319:160]),.movement_o_sum(result_next));
'''
                else:
                    text += ''' for(genvar lane=0;lane<5;lane++)begin:g_lane
   assign result_next[32*lane+:32]=inputs_q[32*lane+:32]+inputs_q[160+32*lane+:32];
 end
'''
            elif kind == 'row':
                if mode == 'actual':
                    text += ''' row_actual u_value(.row_base_addr(inputs_q[31:0]),
   .row_step_bytes(inputs_q[63:32]),.row_wrap_bytes(inputs_q[95:64]),
   .word_addr(inputs_q[127:96]),.addr(inputs_q[159:128]),.row_wrap(inputs_q[160]),
   .next_row_word_match(result_next));
'''
                else:
                    text += ''' logic[31:0] address_value;
 assign address_value=inputs_q[31:0]+(inputs_q[160]?inputs_q[95:64]:inputs_q[63:32]);
 assign result_next={address_value[31:3]==inputs_q[159:131],address_value[31:3]==inputs_q[127:99]};
'''
            else:
                if mode == 'actual':
                    text += ''' horizontal_actual u_value(.pfa_x(inputs_q[34:0]),
   .pf_window_dx_q(inputs_q[67:35]),.pf_fragment_dx_q(inputs_q[100:68]),
   .pf_window_ahead_q(inputs_q[101]),.pf_horizontal_sum(result_next));
'''
                else:
                    text += ''' logic signed[34:0] delta;
 assign delta=inputs_q[101]?35'($signed(inputs_q[67:35])):35'($signed(inputs_q[100:68]));
 assign result_next=inputs_q[34:0]+delta;
'''
            blocks.append(text+'endmodule\n')
            cases[top] = {'top': top, 'options': ['-D', 'SYNTHESIS=1'],
                          'sources': list(map(str, [*helpers, arithmetic, wrappers])),
                          'configuration': f'{input_width} input register bits, {output_width} output register bits; {kind}'}
    wrappers.write_text('\n'.join(blocks))
    (out/'cases.json').write_text(json.dumps(cases, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--vectors', type=int, default=40000)
    args = parser.parse_args()
    root, out = args.source_root.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source = root/'rtl/npu/conv/conv_im2col_frontend.sv'
    geometry_path, geometry = read_module(root, 'geometry')
    addresses_path, addresses = read_module(root, 'conv_descriptor_addresses')
    prefetch_path, prefetch = read_module(root, 'prefetch')
    movement = re.search(r'  for \(genvar source = 0; source < 5; source\+\+\) begin : g_movement_sum\n'
                         r'.*?^  end\n', geometry, re.M | re.S)[0]
    if 'begin : g_next_row_match' not in addresses:
        raise RuntimeError('正式地址模块缺少下一行字匹配实例')
    horizontal_start=prefetch.index('  parallel_prefix_add #(.p_width(16), .p_group_width(4), .p_preserve_groups(1\'b0)) u_prefetch_horizontal_prepare')
    horizontal_end=prefetch.index('`endif',prefetch.index('  assign pf_horizontal_sum =',horizontal_start))+len('`endif')
    horizontal=prefetch[horizontal_start:horizontal_end]
    horizontal = declarations(prefetch, ('prefetch_horizontal_sum', 'unused_prefetch_horizontal_carry',
        'prefetch_horizontal_low_carry','prefetch_horizontal_low_carry_q',
        'unused_prefetch_horizontal_prepare_sum','unused_prefetch_horizontal_low_carry'))+horizontal
    horizontal = horizontal.replace('accepted_coordinate_q[0]', 'pfa_x')
    # 此模型组合完整低位准备和高位修正，管线阶段由完整预取模块的状态回归检查。
    horizontal += '\nassign prefetch_horizontal_low_carry_q=prefetch_horizontal_low_carry;\n'
    phase_assignment = re.search(r'2: begin\s*//[^\n]*\n\s*pf_window_ahead_q <= pf_window_ahead;', prefetch)
    if phase_assignment is None:
        raise RuntimeError('Window mode must be captured in preparation phase 2')
    if not re.search(r'3: begin\s*prefetch_horizontal_low_carry_q <= prefetch_horizontal_low_carry;',prefetch):
        raise RuntimeError('低位进位必须在预取准备阶段三保存')
    arithmetic = out/'arithmetic.sv'
    arithmetic.write_text('''module coordinate_mathematical #(parameter int p_width=35)(
 input logic [p_width-1:0] i_base,i_delta,input logic [15:0] i_limit,
 output logic [p_width-1:0] o_sum,output logic o_valid
);
 assign o_sum=i_base+i_delta;
 assign o_valid=o_sum<p_width'(i_limit);
endmodule

module coordinate_proof #(parameter int p_width=35)(
 input logic [p_width-1:0] i_base,i_delta,input logic [15:0] i_limit,
 output logic equivalent
);
 logic [p_width-1:0] actual_sum,expected_sum;
 logic actual_valid,expected_valid;
 conv_coordinate_step #(.p_width(p_width)) u_actual(.i_base,.i_delta,.i_limit,
   .o_sum(actual_sum),.o_valid(actual_valid));
 coordinate_mathematical #(.p_width(p_width)) u_expected(.i_base,.i_delta,.i_limit,
   .o_sum(expected_sum),.o_valid(expected_valid));
 assign equivalent={actual_sum,actual_valid}=={expected_sum,expected_valid};
endmodule

module movement_actual(input logic [4:0][31:0] movement_i_a,movement_i_b,
 output logic [4:0][31:0] movement_o_sum);
 logic [4:0][31:0] movement_step_delta,movement_wrap_delta;
 logic [4:0] movement_wrap_select;
 assign movement_step_delta=movement_i_b;
 assign movement_wrap_delta=movement_i_b;
 assign movement_wrap_select='0;
'''+movement+'''endmodule

module movement_proof(input logic [4:0][31:0] movement_i_a,movement_i_b,
 output logic equivalent);
 logic [4:0][31:0] movement_o_sum;
 logic [4:0] equal_value;
 movement_actual u_actual(.*);
 for(genvar index=0;index<5;index++)begin:g_reference
   assign equal_value[index]=movement_o_sum[index]==(movement_i_a[index]+movement_i_b[index]);
 end
 assign equivalent=&equal_value;
endmodule

module row_actual #(parameter int p_word_shift=3)(
 input logic [31:0] row_base_addr,row_step_bytes,row_wrap_bytes,word_addr,addr,
 input logic row_wrap,output logic [1:0] next_row_word_match);
 logic [31:0] next_row_addr;
 assign next_row_addr=row_base_addr+(row_wrap?row_wrap_bytes:row_step_bytes);
 conv_descriptor_addresses #(.p_word_shift(p_word_shift)) u_addresses(
  .i_word_addr(word_addr),.i_word_forward(1'b0),.i_addr(addr),
  .i_row_base_addr(row_base_addr),.i_row_group_base(32'd0),
  .i_window_addr(32'd0),.i_window_group_base(32'd0),
  .i_tap_step_bytes(32'd0),.i_tap_wrap_bytes(32'd0),.i_tap_pair_bytes(32'd0),
  .i_row_step_bytes(row_step_bytes),.i_row_wrap_bytes(row_wrap_bytes),
  .i_next_row_addr(next_row_addr),.i_kx0_q(16'd0),.i_row_wrap(row_wrap),
  .i_incoming_tap_wrap(1'b0),.i_q_equal(1'b0),.i_position_previous_row(1'b0),
  .i_position_forward_tap(1'b0),.i_position_backward_tap(1'b0),
  .i_next_position_fast(1'b0),.i_next_tile_fast(1'b0),
  .o_candidate_address(),.o_incoming_word_equal(),.o_incoming_live_word_equal(),
  .o_next_row_word_match(next_row_word_match),.o_incoming_advanced_word_match());
endmodule

module row_proof #(parameter int p_word_shift=3)(
 input logic [31:0] row_base_addr,row_step_bytes,row_wrap_bytes,word_addr,addr,
 input logic row_wrap,output logic equivalent);
 logic [1:0] next_row_word_match,expected;
 logic [31:0] next_row_addr;
 row_actual #(.p_word_shift(p_word_shift)) u_actual(.*);
 assign next_row_addr=row_base_addr+(row_wrap?row_wrap_bytes:row_step_bytes);
 assign expected={next_row_addr[31:p_word_shift]==addr[31:p_word_shift],
                  next_row_addr[31:p_word_shift]==word_addr[31:p_word_shift]};
 assign equivalent=next_row_word_match==expected;
endmodule

module horizontal_actual #(parameter int COORD_W=35)(
 input logic signed [COORD_W-1:0] pfa_x,
 input logic signed [32:0] pf_window_dx_q,pf_fragment_dx_q,
 input logic pf_window_ahead_q,output logic signed [COORD_W-1:0] pf_horizontal_sum);
 logic signed [COORD_W-1:0] pf_horizontal_delta;
'''+horizontal+'''endmodule

module horizontal_proof #(parameter int COORD_W=35)(
 input logic signed [COORD_W-1:0] pfa_x,
 input logic signed [32:0] pf_window_dx_q,pf_fragment_dx_q,
 input logic pf_window_ahead_q,output logic equivalent);
 logic signed [COORD_W-1:0] pf_horizontal_sum,delta;
 horizontal_actual #(.COORD_W(COORD_W)) u_actual(.*);
 assign delta=pf_window_ahead_q?$signed(COORD_W'(pf_window_dx_q)):$signed(COORD_W'(pf_fragment_dx_q));
 assign equivalent=pf_horizontal_sum==(pfa_x+delta);
endmodule
''')
    sources=dependencies(root,[arithmetic])
    helpers=[path for path in sources if path!=arithmetic]
    source_paths=tuple(dict.fromkeys([source,geometry_path,addresses_path,prefetch_path,*helpers]))
    source_hashes={str(path.relative_to(root)):sha(path) for path in source_paths}
    cases = []

    def prove(name, top, parameters='', sequential=False):
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('read_slang -D SYNTHESIS=1 --top '+top+' '+parameters+' '+
                          shlex.join(map(str, [*helpers, arithmetic]))+
                          '\nsetattr -mod -unset keep_hierarchy\nsetattr -unset keep_hierarchy\n'
                          'prep -top '+top+' -flatten\ncheck -assert\n'+
                          ('sat -seq 5 -maxsteps 10 -set-init-zero -tempinduct -verify -prove equivalent 1\n'
                           if sequential else 'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n'))
        run([sys.executable, str(ROOT/'scripts/fpga/open_fpga_synth.py'), '--worker', str(script)], log)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        cases.append({'name': name, 'passed': True, 'log_sha256': sha(log)})

    for width in (33, 35, 40):
        prove(f'coordinate_{width}', 'coordinate_proof', f'-Gp_width={width}')
        prove(f'horizontal_{width}', 'horizontal_proof', f'-GCOORD_W={width}')
    prove('movement', 'movement_proof')
    for shift in range(1, 8):
        prove(f'row_shift{shift}', 'row_proof', f'-Gp_word_shift={shift}')

    bench = out/'tb_arithmetic.sv'
    bench.write_text('''module tb;
 logic [319:0] data_value;
 logic [31:0] random_state;
 logic [34:0] coordinate_sum,expected_coordinate,horizontal_sum,expected_horizontal,delta;
 logic coordinate_valid,expected_valid;
 logic [4:0][31:0] movement_i_a,movement_i_b,movement_o_sum;
 logic [1:0] row_match3,row_match4,expected3,expected4;
 logic [31:0] row_address;
 integer sample_index,word_index,bit_index,lane,check_count=0;
 localparam integer INPUT_W=320;
INPUT_COVERAGE
 conv_coordinate_step u_coordinate(.i_base(data_value[34:0]),.i_delta(data_value[69:35]),
   .i_limit(data_value[85:70]),.o_sum(coordinate_sum),.o_valid(coordinate_valid));
 assign expected_coordinate=data_value[34:0]+data_value[69:35];
 assign expected_valid=expected_coordinate<35'(data_value[85:70]);
 assign movement_i_a=data_value[159:0];
 assign movement_i_b=data_value[319:160];
 movement_actual u_movement(.*);
 row_actual #(.p_word_shift(3)) u_row3(
   .row_base_addr(data_value[31:0]),.row_step_bytes(data_value[63:32]),
   .row_wrap_bytes(data_value[95:64]),.word_addr(data_value[127:96]),
   .addr(data_value[159:128]),.row_wrap(data_value[160]),.next_row_word_match(row_match3));
 row_actual #(.p_word_shift(4)) u_row4(
   .row_base_addr(data_value[31:0]),.row_step_bytes(data_value[63:32]),
   .row_wrap_bytes(data_value[95:64]),.word_addr(data_value[127:96]),
   .addr(data_value[159:128]),.row_wrap(data_value[160]),.next_row_word_match(row_match4));
 assign row_address=data_value[31:0]+(data_value[160]?data_value[95:64]:data_value[63:32]);
 assign expected3={row_address[31:3]==data_value[159:131],row_address[31:3]==data_value[127:99]};
 assign expected4={row_address[31:4]==data_value[159:132],row_address[31:4]==data_value[127:100]};
 horizontal_actual u_horizontal(.pfa_x(data_value[34:0]),.pf_window_dx_q(data_value[67:35]),
   .pf_fragment_dx_q(data_value[100:68]),.pf_window_ahead_q(data_value[101]),
   .pf_horizontal_sum(horizontal_sum));
 assign delta=data_value[101]?35'($signed(data_value[67:35])):35'($signed(data_value[100:68]));
 assign expected_horizontal=data_value[34:0]+delta;
 function automatic [31:0] random_word(input logic unused);
   random_state=random_state^(random_state<<13);
   random_state=random_state^(random_state>>17);
   random_state=random_state^(random_state<<5);
   return random_state;
 endfunction
 task check_vector;
 begin
   #1;observe_inputs();
   if({coordinate_sum,coordinate_valid}!=={expected_coordinate,expected_valid})
     $fatal(1,"coordinate sample %0d",sample_index);
   for(lane=0;lane<5;lane++)
     if(movement_o_sum[lane]!==32'(movement_i_a[lane]+movement_i_b[lane]))
       $fatal(1,"movement sample %0d lane %0d",sample_index,lane);
   if(row_match3!==expected3||row_match4!==expected4)$fatal(1,"row sample %0d",sample_index);
   if(horizontal_sum!==expected_horizontal)$fatal(1,"horizontal sample %0d",sample_index);
   check_count++;
 end
 endtask
 initial begin
   random_state=32'h2a8637b1;
   initialize_input_coverage();
   for(integer state_index=0;state_index<4;state_index++)begin
     for(integer input_index=0;input_index<INPUT_W;input_index++)begin
       data_value='0;
       case(state_index)
         0:data_value[input_index]=0;1:data_value[input_index]=1;
         2:data_value[input_index]=1'bx;3:data_value[input_index]=1'bz;
       endcase
       check_vector();
     end
   end
   for(sample_index=0;sample_index<VECTORS;sample_index++)begin
     for(word_index=0;word_index<10;word_index++)data_value[word_index*32+:32]=random_word(1'b0);
     if(sample_index%2==1)begin
       bit_index=int'(random_word(1'b0)%320);
       data_value[bit_index]=sample_index%4==1?1'bx:1'bz;
     end
     if(sample_index%11==0)begin
       data_value[34:0]=35'h7ffffffff;data_value[69:35]=35'd1;
     end
     check_vector();
   end
   check_input_coverage();
   $display("CRITICAL_ARITHMETIC_PASS vectors=%0d comparisons=%0d",check_count,9*check_count);
   $finish;
 end
endmodule
'''.replace('VECTORS', str(args.vectors)).replace('INPUT_COVERAGE',
    coverage_declarations('INPUT_W')+coverage_tasks('INPUT_W','data_value')))
    executable = out/'arithmetic.vvp'
    run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
         *map(str, helpers), str(arithmetic), str(bench)], out/'compile.log')
    run(['vvp', str(executable)], out/'numeric.log', timeout=600)
    numeric=(out/'numeric.log').read_text()
    match=re.search(r'CRITICAL_ARITHMETIC_PASS vectors=(\d+) comparisons=(\d+)',numeric)
    if match is None:
        raise RuntimeError(str(out/'numeric.log'))
    if source_hashes != {str(p.relative_to(root)): sha(p) for p in source_paths}:
        raise RuntimeError('Source changed during validation')
    prepare_mapping(out, helpers, arithmetic)
    report = {'passed': True, 'source_sha256': source_hashes, 'formal': cases,
              'four_state': {'passed': True, 'vectors': int(match[1]), 'comparisons': int(match[2]),
                             'input_coverage':parse_coverage(numeric),
                             'log_sha256': sha(out/'numeric.log')},
              'scope': '坐标完整和值与范围、五种地址移动、正式地址模块的两种字宽行字匹配，以及预取横坐标两阶段合成的完整组合数学表达式',
              'prefetch_stage_validation':'test/frontend_address_arithmetic/run.py 完整预取状态及公开输出等价'}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'formal_cases': len(cases), 'four_state_vectors': int(match[1]),
                      'four_state_comparisons': int(match[2])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
