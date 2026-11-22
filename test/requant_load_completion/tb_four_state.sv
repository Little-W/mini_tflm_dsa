// SPDX-License-Identifier: Apache-2.0
// 比较完整偏移范围、突发边界与未知位条件下的命令准备资格。
module tb;
 logic [31:0] need,offset,seed=32'h571ca389;
 wire [11:0] expected,observed;
 integer checks=0,unknown_inputs=0,unknown_results=0;
 function automatic [31:0] random_word;
  seed=seed*32'd1664525+32'd1013904223;random_word=seed;
 endfunction
arithmetic_reference #(32,1) r0(.quant_need_load_r(need),.load_offset(offset),.result(expected[0]),.chunk());
 arithmetic_current #(32,1) c0(.quant_need_load_r(need),.load_offset(offset),.result(observed[0]),.chunk());
arithmetic_reference #(32,3) r1(.quant_need_load_r(need),.load_offset(offset),.result(expected[1]),.chunk());
 arithmetic_current #(32,3) c1(.quant_need_load_r(need),.load_offset(offset),.result(observed[1]),.chunk());
arithmetic_reference #(32,16) r2(.quant_need_load_r(need),.load_offset(offset),.result(expected[2]),.chunk());
 arithmetic_current #(32,16) c2(.quant_need_load_r(need),.load_offset(offset),.result(observed[2]),.chunk());
arithmetic_reference #(32,32) r3(.quant_need_load_r(need),.load_offset(offset),.result(expected[3]),.chunk());
 arithmetic_current #(32,32) c3(.quant_need_load_r(need),.load_offset(offset),.result(observed[3]),.chunk());
arithmetic_reference #(32,256) r4(.quant_need_load_r(need),.load_offset(offset),.result(expected[4]),.chunk());
 arithmetic_current #(32,256) c4(.quant_need_load_r(need),.load_offset(offset),.result(observed[4]),.chunk());
arithmetic_reference #(32,1024) r5(.quant_need_load_r(need),.load_offset(offset),.result(expected[5]),.chunk());
 arithmetic_current #(32,1024) c5(.quant_need_load_r(need),.load_offset(offset),.result(observed[5]),.chunk());
arithmetic_reference #(1,16) r6(.quant_need_load_r(need),.load_offset(offset),.result(expected[6]),.chunk());
 arithmetic_current #(1,16) c6(.quant_need_load_r(need),.load_offset(offset),.result(observed[6]),.chunk());
arithmetic_reference #(4,16) r7(.quant_need_load_r(need),.load_offset(offset),.result(expected[7]),.chunk());
 arithmetic_current #(4,16) c7(.quant_need_load_r(need),.load_offset(offset),.result(observed[7]),.chunk());
arithmetic_reference #(8,16) r8(.quant_need_load_r(need),.load_offset(offset),.result(expected[8]),.chunk());
 arithmetic_current #(8,16) c8(.quant_need_load_r(need),.load_offset(offset),.result(observed[8]),.chunk());
arithmetic_reference #(24,16) r9(.quant_need_load_r(need),.load_offset(offset),.result(expected[9]),.chunk());
 arithmetic_current #(24,16) c9(.quant_need_load_r(need),.load_offset(offset),.result(observed[9]),.chunk());
arithmetic_reference #(40,16) r10(.quant_need_load_r(need),.load_offset(offset),.result(expected[10]),.chunk());
 arithmetic_current #(40,16) c10(.quant_need_load_r(need),.load_offset(offset),.result(observed[10]),.chunk());
arithmetic_reference #(64,16) r11(.quant_need_load_r(need),.load_offset(offset),.result(expected[11]),.chunk());
 arithmetic_current #(64,16) c11(.quant_need_load_r(need),.load_offset(offset),.result(observed[11]),.chunk());
 initial begin
  for(integer sample=0;sample<32768;sample++)begin
   need=random_word();offset=random_word();
   case(sample%16)
    0:begin need=0;offset=0;end
    1:need=offset;
    2:need=offset+16;
    3:need=offset+17;
    4:begin offset=32'hffffff00;need=32'hffffffff;end
    5:begin offset=0;need=32'(sample/16);end
    6:begin offset=32'(sample/16);need=16;end
    7:begin offset=0;need=32'h0000100x;end
    8:need[(sample/16)%32]=1'bx;
    9:offset[(sample/16)%32]=1'bz;
    10:begin need=offset+1;need[(sample/16)%32]=1'bz;end
    11:begin offset=0;need[(sample/16)%32]=1'bx;end
    12:begin need=0;offset[(sample/16)%32]=1'bz;end
    13:begin offset[(sample/16)%32]=1'bx;need[(sample/16+13)%32]=1'bz;end
    14:begin offset=32'hffffffff;need[(sample/16)%32]=1'bx;end
    default:begin end
   endcase
   #1;
   if(expected!==observed)$fatal(1,"Arithmetic differs sample=%0d need=%h offset=%h expected=%h observed=%h",sample,need,offset,expected,observed);
   checks=checks+12;
   if((^{need,offset})===1'bx)unknown_inputs++;
   for(integer i=0;i<12;i++)if(observed[i]===1'bx)unknown_results++;
  end
  $display("REQUANT_COMMAND_ARITHMETIC_PASS samples=32768 checks=%0d unknown_inputs=%0d unknown_results=%0d",checks,unknown_inputs,unknown_results);
  $finish;
 end
 endmodule
