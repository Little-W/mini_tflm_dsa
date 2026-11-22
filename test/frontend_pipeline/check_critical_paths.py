#!/usr/bin/env python3
"""验证实际前端的坐标、行地址和预取运算，并生成局部综合输入。"""
import argparse
import hashlib
import json
from pathlib import Path
from source_sections import read_module, declarations
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


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
    helpers = [root/'rtl/common/add_equal.sv', root/'rtl/common/parallel_prefix_add.sv',
               root/'rtl/npu/conv/conv_coordinate_step.sv']
    geometry_path, geometry = read_module(root, 'geometry')
    descriptor_path, descriptor = read_module(root, 'descriptor')
    prefetch_path, prefetch = read_module(root, 'prefetch')
    source_paths = (source, geometry_path, descriptor_path, prefetch_path, *helpers)
    source_hashes = {str(p.relative_to(root)): sha(p) for p in source_paths}
    movement = re.search(r'  for \(genvar source = 0; source < 5; source\+\+\) begin : g_movement_sum\n'
                         r'.*?^  end\n', geometry, re.M | re.S)[0]
    row_match = section(descriptor, '  for (genvar target = 0; target < 2; target++) begin : g_next_row_match',
                        '    assign incoming_window_word_match') + '  end\n'
    horizontal = section(prefetch, '  assign pf_horizontal_delta =', '  // 较大通道数按缓存行预测')
    horizontal = declarations(prefetch, ('prefetch_horizontal_sum', 'unused_prefetch_horizontal_carry'))+horizontal
    horizontal = horizontal.replace('accepted_coordinate_q[0]', 'pfa_x')
    ahead = section(prefetch, '  assign pf_window_ahead =', '  assign pf_horizontal_delta =')
    ahead = ahead.replace('tile_extent_q[0]', 'pfa_rows').replace('tile_extent_q[1]', 'pfa_cols')
    phase_assignment = re.search(r'2: begin\s*//[^\n]*\n\s*pf_window_ahead_q <= pf_window_ahead;', prefetch)
    if phase_assignment is None:
        raise RuntimeError('Window mode must be captured in preparation phase 2')
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
'''+row_match+'''endmodule

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
    mode = out/'prefetch_mode.sv'
    # 接收阶段保存上下文；配置只在预取空闲时接受，阶段二到阶段三之间上下文保持。
    mode.write_text('''module prefetch_mode_proof(
 input logic clk,rst_n,configure,accept,
 input logic [15:0] input_c,group_c,stride_h,stride_w,
 input logic windowed,input logic [31:0] input_rows,input_cols,
 output logic equivalent);
 typedef struct packed {logic windowed;logic[15:0]input_c,group_c,stride_h,stride_w;} cfg_t;
 cfg_t c;
 logic [31:0] pfa_rows,pfa_cols;
 logic [3:0] phase;
 logic pf_stream_lookahead,pf_window_ahead,pf_window_ahead_q;
 assign pf_stream_lookahead=c.windowed&&c.input_c>=16'd16;
'''+ahead+'''
 always_ff @(posedge clk)begin
   if(!rst_n)begin phase<=4'd0;c<='0;end
   else if(configure&&phase==4'd0)begin
     c<={windowed,input_c,group_c,stride_h,stride_w};
   end else case(phase)
     0:if(accept)begin pfa_rows<=input_rows;pfa_cols<=input_cols;phase<=4'd1;end
     1:phase<=4'd2;
     2:begin pf_window_ahead_q<=pf_window_ahead;phase<=4'd3;end
     3:phase<=4'd4;
     4:phase<=4'd5;
     5:phase<=4'd6;
     6:phase<=4'd7;
     7:phase<=4'd8;
     default:phase<=4'd0;
   endcase
 end
 assign equivalent=phase!=4'd3 || pf_window_ahead_q==pf_window_ahead;
endmodule
''')
    cases = []

    def prove(name, top, parameters='', sequential=False):
        script, log = out/(name+'.ys'), out/(name+'.log')
        script.write_text('read_slang -D SYNTHESIS=1 --top '+top+' '+parameters+' '+
                          shlex.join(map(str, [*helpers, arithmetic, mode]))+
                          '\nprep -top '+top+' -flatten\ncheck -assert\n'+
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
    prove('prefetch_mode', 'prefetch_mode_proof', sequential=True)

    bench = out/'tb_arithmetic.sv'
    bench.write_text('''module tb;
 logic [319:0] data_value;
 logic [31:0] random_state;
 logic [34:0] coordinate_sum,expected_coordinate,horizontal_sum,expected_horizontal,delta;
 logic coordinate_valid,expected_valid;
 logic [4:0][31:0] movement_i_a,movement_i_b,movement_o_sum;
 logic [1:0] row_match3,row_match4,expected3,expected4;
 logic [31:0] row_address;
 integer sample_index,word_index,bit_index,lane;
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
 initial begin
   random_state=32'h2a8637b1;
   for(sample_index=0;sample_index<VECTORS;sample_index++)begin
     for(word_index=0;word_index<10;word_index++)data_value[word_index*32+:32]=random_word(1'b0);
     if(sample_index%2==1)begin
       bit_index=int'(random_word(1'b0)%320);
       data_value[bit_index]=sample_index%4==1?1'bx:1'bz;
     end
     if(sample_index%11==0)begin
       data_value[34:0]=35'h7ffffffff;data_value[69:35]=35'd1;
     end
     #1;
     if({coordinate_sum,coordinate_valid}!=={expected_coordinate,expected_valid})
       $fatal(1,"coordinate sample %0d",sample_index);
     for(lane=0;lane<5;lane++)
       if(movement_o_sum[lane]!==32'(movement_i_a[lane]+movement_i_b[lane]))
         $fatal(1,"movement sample %0d lane %0d",sample_index,lane);
     if(row_match3!==expected3||row_match4!==expected4)$fatal(1,"row sample %0d",sample_index);
     if(horizontal_sum!==expected_horizontal)$fatal(1,"horizontal sample %0d",sample_index);
   end
   $display("CRITICAL_ARITHMETIC_PASS vectors=%0d comparisons=%0d",VECTORS,9*VECTORS);
   $finish;
 end
endmodule
'''.replace('VECTORS', str(args.vectors)))
    executable = out/'arithmetic.vvp'
    run(['iverilog', '-g2012', '-s', 'tb', '-o', str(executable),
         *map(str, helpers), str(arithmetic), str(bench)], out/'compile.log')
    run(['vvp', str(executable)], out/'numeric.log', timeout=600)
    if 'CRITICAL_ARITHMETIC_PASS' not in (out/'numeric.log').read_text():
        raise RuntimeError(str(out/'numeric.log'))
    if source_hashes != {str(p.relative_to(root)): sha(p) for p in source_paths}:
        raise RuntimeError('Source changed during validation')
    prepare_mapping(out, helpers, arithmetic)
    report = {'passed': True, 'source_sha256': source_hashes, 'formal': cases,
              'four_state': {'passed': True, 'vectors': args.vectors, 'comparisons': 9*args.vectors,
                             'log_sha256': sha(out/'numeric.log')},
              'scope': '坐标完整和值与范围、五种地址移动、两种字宽的行字匹配、预取横坐标与阶段二模式保存关系'}
    (out/'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'passed': True, 'formal_cases': len(cases), 'four_state_vectors': args.vectors,
                      'four_state_comparisons': 9*args.vectors}, ensure_ascii=False))


if __name__ == '__main__':
    main()
