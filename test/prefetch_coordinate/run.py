#!/usr/bin/env python3
"""验证预取行边界的进位关系、阶段保存和完整坐标选择。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, output, cwd, timeout=180):
    with output.open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                cwd=cwd, timeout=timeout)
    if result.returncode:
        raise RuntimeError(str(output))


def section(text, start, end):
    begin = text.index(start)
    return text[begin:text.index(end, begin)]


PORTS = '''(
 input conv_im2col_pkg::conv_cfg_t i_c,
 input logic signed [34:0] accepted_coordinate_q [2],
 input logic [31:0] pf_step_q,prefetch_wrap_base_q,pf_distance_q,
 input logic prefetch_base_no_borrow_q,
 input logic prefetch_horizontal_low_carry_q,
 input logic [31:0] pf_y_base_q,pf_y_wrapped_q,pf_kernel_advance_q,
 input logic pf_window_ahead_q,
 input logic signed [32:0] pf_window_dx_q,pf_fragment_dx_q,
 input logic [16:0] pf_window_dy_q,
 input logic [31:0] tile_extent_q [2],
 input logic [31:0] output_coordinate_q [2],
 input logic [15:0] i_last_output_col_q,i_second_last_col_q,
 output logic [31:0] pf_x,pf_y,
 output logic signed [34:0] complete_sum,
 output logic crosses_row
);
'''


def model(text, name):
    arithmetic = section(text, '  assign prefetch_wrap_i_a =',
                         '  // 核行片段和跨步窗口共用横坐标加法')
    horizontal = section(text, '  assign pf_horizontal_delta =',
                         '  // 较大通道数按缓存行预测')
    choice = section(text, '  assign pf_stream_lookahead =', '    pf_coordinate_valid=') + '  end\n'
    flag = 'pf_crosses_row' if 'logic pf_crosses_row;' in text else "(prefetch_next_x>=32'(i_c.input_w))"
    return '`default_nettype none\nmodule '+name+PORTS+'''
 localparam integer p_coord_w=35;
 logic [31:0] prefetch_wrap_i_a,prefetch_wrap_i_b,prefetch_wrap_base;
 logic [31:0] prefetch_next_x,prefetch_wrapped_x,pf_distance;
 logic [2:0] prefetch_x_carry,unused_prefetch_x_carry;
 logic [2:0][15:0] prefetch_range_a,prefetch_range_b,unused_prefetch_range_sum;
 logic [1:0] prefetch_high_zero;
 logic prefetch_next_high_zero;
 logic pf_crosses_row,pf_stream_lookahead,pf_ahead_two,pf_wrap_once,pf_wrap_twice;
 logic signed [34:0] pf_horizontal_delta,pf_horizontal_sum,pf_wrap_x,pf_window_x,pf_window_y;
 logic [34:0] prefetch_horizontal_sum;
 logic unused_prefetch_horizontal_carry;
 logic unused_prefetch_horizontal_low_carry;
 logic prefetch_horizontal_negative,prefetch_horizontal_sign_carry,unused_prefetch_sign_equal;
 logic [33:0] unused_prefetch_sign_sum;
 logic prefetch_horizontal_low_carry;
 logic [2:0] prefetch_horizontal_high_generate,prefetch_horizontal_high_propagate;
 logic [3:0] prefetch_horizontal_high_carry;
'''+arithmetic+horizontal+choice+' assign complete_sum=pf_horizontal_sum;\n assign crosses_row='+flag+';\nendmodule\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--out', type=Path, default=Path(__file__).resolve().parents[2]/'build/prefetch_coordinate')
    parser.add_argument('--vectors', type=int, default=40000)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    root, out = args.repo.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    source_root = args.source_root.resolve() if args.source_root else root
    candidate = source_root/'rtl/npu/conv/conv_im2col_prefetch.sv'
    reference = base/'prefetch_coordinate_reference.sv'
    helper = source_root/'rtl/common/parallel_prefix_add.sv'
    compare = source_root/'rtl/common/unsigned_compare.sv'
    equal = source_root/'rtl/common/add_equal.sv'
    package = source_root/'rtl/npu/conv/conv_im2col_pkg.sv'
    sources = (candidate, reference, helper, compare, equal, package)
    range_low16 = int('g_prefetch_range_carry' in candidate.read_text())
    hashes = {str(path): digest(path) for path in sources}
    models = out/'selection.sv'
    models.write_text(reference.read_text()+model(candidate.read_text(), 'selection_candidate'))
    proof = out/'proof.sv'
    proof.write_text('''module carry_identity #(parameter integer WIDTH=32)(
 input logic [WIDTH-1:0] a,b,step,output logic equivalent
);
 wire [WIDTH:0] base_sum={1'b0,a}+{1'b0,~b}+(WIDTH+1)'(1);
 wire [WIDTH:0] next_sum={1'b0,a}+{1'b0,step};
 wire [WIDTH:0] wrapped_sum={1'b0,base_sum[WIDTH-1:0]}+{1'b0,step};
 wire crosses_row=base_sum[WIDTH]^next_sum[WIDTH]^wrapped_sum[WIDTH];
 assign equivalent=crosses_row==(next_sum[WIDTH-1:0]>=b);
endmodule

module sign_proof(input logic [34:0] a,delta,output logic equivalent);
 wire [34:0] expected=a+delta;
 wire [16:0] prepared_low={1'b0,a[15:0]}+{1'b0,delta[15:0]};
 wire [15:0] low_sum;
 wire [18:0] high_sum;
 wire unused_low_carry,unused_high_carry;
 parallel_prefix_add #(.p_width(16),.p_group_width(4),.p_preserve_groups(1)) u_low (
  .i_a(a[15:0]),.i_b(delta[15:0]),.i_carry(1'b0),.o_sum(low_sum),.o_carry(unused_low_carry));
 parallel_prefix_add #(.p_width(19),.p_group_width(4),.p_preserve_groups(1)) u_high (
  .i_a(a[34:16]),.i_b(delta[34:16]),.i_carry(prepared_low[16]),
  .o_sum(high_sum),.o_carry(unused_high_carry));
 assign equivalent=({high_sum,low_sum}==expected);
endmodule

module selection_proof'''+PORTS.replace('output logic [31:0] pf_x,pf_y,\n output logic crosses_row',
                                      'output logic equivalent').replace('output logic [31:0] pf_x,pf_y,\n output logic signed [34:0] complete_sum,\n output logic crosses_row',
                                      'output logic equivalent').replace('pf_step_q,prefetch_wrap_base_q,pf_distance_q',
                                      'pf_step_q,pf_distance_q').replace(' input logic prefetch_base_no_borrow_q,\n','').replace(' input logic prefetch_horizontal_low_carry_q,\n','')+'''
 wire [31:0] prefetch_wrap_base_q;
 wire prefetch_base_no_borrow_q;
 wire base_no_borrow32;
 parallel_prefix_add #(.p_width(32),.p_group_width(4),.p_preserve_groups(1)) u_base (
  .i_a(accepted_coordinate_q[0][31:0]),.i_b(~{16'd0,i_c.input_w}),.i_carry(1'b1),
  .o_sum(prefetch_wrap_base_q),.o_carry(base_no_borrow32));
 wire [16:0] base_low={1'b0,accepted_coordinate_q[0][15:0]}+{1'b0,~i_c.input_w}+17'd1;
 assign prefetch_base_no_borrow_q=RANGE_LOW16 ? base_low[16] : base_no_borrow32;
 wire signed [34:0] captured_delta=pf_window_ahead_q ? 35'(pf_window_dx_q) : 35'(pf_fragment_dx_q);
 wire [16:0] captured_low_sum={1'b0,accepted_coordinate_q[0][15:0]}+{1'b0,captured_delta[15:0]};
 wire prefetch_horizontal_low_carry_q=captured_low_sum[16];
 wire [31:0] reference_x,reference_y,candidate_x,candidate_y;
 wire signed [34:0] reference_sum,candidate_sum;
 wire reference_flag,candidate_flag;
 prefetch_coordinate_reference u_reference(.*,.pf_x(reference_x),.pf_y(reference_y),.complete_sum(reference_sum),.crosses_row(reference_flag));
 selection_candidate u_candidate(.*,.pf_x(candidate_x),.pf_y(candidate_y),.complete_sum(candidate_sum),.crosses_row(candidate_flag));
 assign equivalent={reference_flag,reference_x,reference_y,reference_sum}=={candidate_flag,candidate_x,candidate_y,candidate_sum};
endmodule

module phase_proof(input logic clk,rst_n,configuration,accept,
 input logic [31:0] a,step,input logic [15:0] width,
 input logic [34:0] coordinate_a,delta,output logic equivalent);
 logic [3:0] phase;
 logic [31:0] accepted_x,step_q,base_q;
 logic [15:0] width_q;
 logic no_borrow_q;
 logic [34:0] coordinate_q,delta_q;
 logic halfword_carry_q;
 wire [32:0] base_sum={1'b0,accepted_x}+{1'b0,~{16'd0,width_q}}+33'd1;
 wire [32:0] next_sum={1'b0,accepted_x}+{1'b0,step_q};
 wire [32:0] wrapped_sum={1'b0,base_q}+{1'b0,step_q};
 wire [16:0] base_low={1'b0,accepted_x[15:0]}+{1'b0,~width_q}+17'd1;
 wire [16:0] next_low={1'b0,accepted_x[15:0]}+{1'b0,step_q[15:0]};
 wire [16:0] wrapped_low={1'b0,base_q[15:0]}+{1'b0,step_q[15:0]};
 wire saved_relation=(base_q==base_sum[31:0]) &&
   (no_borrow_q==(RANGE_LOW16 ? base_low[16] : base_sum[32]));
 wire crosses_row=RANGE_LOW16 ? ((|next_sum[31:16]) | (no_borrow_q^next_low[16]^wrapped_low[16])) :
   (no_borrow_q^next_sum[32]^wrapped_sum[32]);
 wire [16:0] next_halfword={1'b0,coordinate_q[15:0]}+{1'b0,delta[15:0]};
 wire [15:0] coordinate_low=coordinate_q[15:0]+delta_q[15:0];
 wire [18:0] coordinate_high=coordinate_q[34:16]+delta_q[34:16]+19'(halfword_carry_q);
 assign equivalent=(phase<2 || phase>8 || saved_relation) &&
   (phase!=3 || ((crosses_row==(next_sum[31:0]>=32'(width_q))) &&
                ({coordinate_high,coordinate_low}==(coordinate_q+delta_q))));
 always @(posedge clk) begin
   if(!rst_n) phase<=0;
   else if(configuration) phase<=0;
   else case(phase)
     0:if(accept) phase<=1;
     1:phase<=2;2:phase<=3;3:phase<=4;4:phase<=5;
     5:phase<=6;6:phase<=7;7:phase<=8;default:phase<=0;
   endcase
   if(!rst_n) begin end
   else if(configuration) width_q<=width;
   else case(phase)
     0:if(accept) begin accepted_x<=a;coordinate_q<=coordinate_a;end
     1:begin base_q<=base_sum[31:0];no_borrow_q<=RANGE_LOW16 ? base_low[16] : base_sum[32];end
     2:begin step_q<=step;delta_q<=delta;halfword_carry_q<=next_halfword[16];end
     default:;
   endcase
 end
endmodule
'''.replace('RANGE_LOW16', str(range_low16)))
    runs = []
    cases = [('identity8','carry_identity','-G WIDTH=8',False),
             ('identity32','carry_identity','-G WIDTH=32',False),
             ('sign35','sign_proof','',False),
             ('selection','selection_proof','',False),('phase','phase_proof','',True)]
    for name, top, options, sequential in cases:
        script, log = out/(name+'.ys'), out/(name+'.log')
        commands = 'read_slang -D SYNTHESIS=1 --top '+top+' '+options+' '+shlex.join(map(str,(package,helper,compare,equal,models,proof)))
        commands += '\nprep -top '+top+' -flatten\ncheck -assert\n'
        commands += ('sat -seq 12 -tempinduct -maxsteps 20 -set-at 1 rst_n 0 '
                     '-verify -prove equivalent 1 -show-inputs -show-outputs\n' if sequential else
                     'sat -verify -prove equivalent 1 -show-inputs -show-outputs\n')
        script.write_text(commands)
        run([sys.executable,str(root/'scripts/fpga/open_fpga_synth.py'),'--worker',str(script)],log,root)
        if 'SUCCESS!' not in log.read_text():
            raise RuntimeError(str(log))
        runs.append({'name':name,'passed':True,'log_sha256':digest(log)})
    bench = out/'tb.sv'
    bench.write_text('''module tb;
 conv_im2col_pkg::conv_cfg_t i_c;
 logic signed [34:0] accepted_coordinate_q [2];
 logic [31:0] pf_step_q,pf_distance_q;
 wire [31:0] prefetch_wrap_base_q;
 wire prefetch_base_no_borrow_q;
 wire base_no_borrow32;
 logic [31:0] pf_y_base_q,pf_y_wrapped_q,pf_kernel_advance_q;
 logic pf_window_ahead_q;
 logic signed [32:0] pf_window_dx_q,pf_fragment_dx_q;
 logic [16:0] pf_window_dy_q;
 logic [31:0] tile_extent_q [2],output_coordinate_q [2];
 logic [15:0] i_last_output_col_q,i_second_last_col_q;
 wire [31:0] reference_x,reference_y,candidate_x,candidate_y;
 wire signed [34:0] reference_sum,candidate_sum;
 wire reference_flag,candidate_flag;
 integer count=0,unknowns=0;
 logic [31:0] random_state=32'h8919cafd;
 logic [$bits(i_c)-1:0] cfg_bits;
 parallel_prefix_add #(.p_width(32),.p_group_width(4),.p_preserve_groups(1)) u_base (
  .i_a(accepted_coordinate_q[0][31:0]),.i_b(~{16'd0,i_c.input_w}),.i_carry(1'b1),
  .o_sum(prefetch_wrap_base_q),.o_carry(base_no_borrow32));
 wire [16:0] base_low={1'b0,accepted_coordinate_q[0][15:0]}+{1'b0,~i_c.input_w}+17'd1;
 assign prefetch_base_no_borrow_q=RANGE_LOW16 ? base_low[16] : base_no_borrow32;
 wire signed [34:0] captured_delta=pf_window_ahead_q ? 35'(pf_window_dx_q) : 35'(pf_fragment_dx_q);
 wire [16:0] captured_low_sum={1'b0,accepted_coordinate_q[0][15:0]}+{1'b0,captured_delta[15:0]};
 wire prefetch_horizontal_low_carry_q=captured_low_sum[16];
 prefetch_coordinate_reference u_reference(.*,.pf_x(reference_x),.pf_y(reference_y),.complete_sum(reference_sum),.crosses_row(reference_flag));
 selection_candidate u_candidate(.*,.pf_x(candidate_x),.pf_y(candidate_y),.complete_sum(candidate_sum),.crosses_row(candidate_flag));
 function automatic [31:0] random_word(input logic unused);
   random_state=random_state^(random_state<<13);
   random_state=random_state^(random_state>>17);
   random_state=random_state^(random_state<<5);
   return random_state;
 endfunction
 initial begin
   for(integer index=0;index<VECTORS;index=index+1) begin
     for(integer bit_index=0;bit_index<$bits(i_c);bit_index=bit_index+1)
       cfg_bits[bit_index]=1'(random_word(0));
     i_c=cfg_bits;
     accepted_coordinate_q[0]={3'(random_word(0)),random_word(0)};
     accepted_coordinate_q[1]={3'(random_word(0)),random_word(0)};
     pf_step_q=random_word(0);pf_distance_q=random_word(0);
     pf_y_base_q=random_word(0);pf_y_wrapped_q=random_word(0);
     pf_kernel_advance_q=random_word(0);pf_window_ahead_q=1'(random_word(0));
     pf_window_dx_q={1'(random_word(0)),random_word(0)};
     pf_fragment_dx_q={1'(random_word(0)),random_word(0)};
     pf_window_dy_q=17'(random_word(0));
     tile_extent_q[0]=random_word(0);tile_extent_q[1]=random_word(0);
     output_coordinate_q[0]=random_word(0);output_coordinate_q[1]=random_word(0);
     i_last_output_col_q=16'(random_word(0));i_second_last_col_q=16'(random_word(0));
     if(index%4==0)begin
       case(index%8)
         0:begin accepted_coordinate_q[0]=0;pf_step_q=0;i_c.input_w=0;end
         4:begin accepted_coordinate_q[0]=35'h0ffffffff;pf_step_q=1;i_c.input_w=1;end
       endcase
     end
     if(index%3==0)begin
       i_c.windowed=1;i_c.input_c=8;i_c.kernel_w=3;i_c.kernel_h=3;
       i_c.dilation_w=1;i_c.dilation_h=1;tile_extent_q[0]=1;
       tile_extent_q[1]=2;i_c.group_c=4;pf_kernel_advance_q=4;
     end
     if(index%2==1)begin
       case(index%10)
         1:accepted_coordinate_q[0][random_word(0)%35]=1'bx;
         3:pf_step_q[random_word(0)%32]=1'bz;
         5:i_c.input_w[3:0]=4'bxzxz;
         7:begin pf_window_ahead_q=1'bx;accepted_coordinate_q[1][0]=1'bz;end
         9:begin pf_stream_controls();end
       endcase
       unknowns=unknowns+1;
     end
     #2;
     if({reference_flag,reference_x,reference_y,reference_sum}!=={candidate_flag,candidate_x,candidate_y,candidate_sum})
       $fatal(1,"Prefetch selection differs at vector %0d",index);
     count=count+4;
   end
   $display("PREFETCH_CARRY_PASS vectors=%0d unknown_vectors=%0d comparisons=%0d",VECTORS,unknowns,count);
   $finish;
 end
 task pf_stream_controls;
   i_c.windowed=1'bz;pf_window_dx_q[7]=1'bx;pf_fragment_dx_q[0]=1'bz;
 endtask
endmodule
'''.replace('VECTORS', str(args.vectors)).replace('RANGE_LOW16', str(range_low16)))
    executable = out/'simulation.vvp'
    run(['iverilog','-g2012','-s','tb','-o',str(executable),str(package),str(helper),str(compare),str(equal),
         str(models),str(bench)],out/'build.log',root)
    run(['vvp',str(executable)],out/'simulation.log',root,timeout=180)
    match = re.search(r'PREFETCH_CARRY_PASS vectors=(\d+) unknown_vectors=(\d+) comparisons=(\d+)',
                      (out/'simulation.log').read_text())
    if not match:
        raise RuntimeError(str(out/'simulation.log'))
    if hashes != {str(path):digest(path) for path in sources}:
        raise RuntimeError('Source changed during validation')
    summary = {'passed':True,'source_sha256':hashes,'formal':runs,
               'four_state':{'passed':True,'vectors':int(match[1]),'unknown_vectors':int(match[2]),
                             'comparisons':int(match[3]),'log_sha256':digest(out/'simulation.log')},
               'scope':'任意 32 位模加法关系、完整 35 位分段求和、实际坐标选择表达式，以及配置取消与复位的阶段保持关系'}
    (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    main()
