// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_scalar_dsp_pair;
  logic clk=0, enable=0;
  logic signed [31:0] operand_a='0, operand_b='0;
  wire signed [63:0] product [8], reference_product [8];
  integer samples=0, checks=0;

  for (genvar configuration=0; configuration<8; configuration++) begin : g_configuration
    registered_multiplier_s32 #(
      .p_input_register((configuration>>2)&1),
      .p_b_input_register((configuration>>1)&1),
      .p_use_dsp(configuration&1)
    ) u_candidate (.clk, .i_en(enable), .i_a(operand_a), .i_b(operand_b), .o_product(product[configuration]));
    registered_multiplier_s32_reference #(
      .p_input_register((configuration>>2)&1),
      .p_b_input_register((configuration>>1)&1),
      .p_use_dsp(configuration&1)
    ) u_reference (.clk, .i_en(enable), .i_a(operand_a), .i_b(operand_b), .o_product(reference_product[configuration]));
  end

  task automatic sample(input logic [31:0] lhs, rhs, input logic enabled);
    operand_a=lhs;
    operand_b=rhs;
    enable=enabled;
    clk=0;
    #1;
    clk=1;
    #1;
    for (integer configuration=0; configuration<8; configuration++) begin
      if (product[configuration] !== reference_product[configuration])
        $fatal(1,"乘积不同 configuration=%0d sample=%0d actual=%h expected=%h",
          configuration,samples,product[configuration],reference_product[configuration]);
      checks++;
    end
    samples++;
    clk=0;
    #1;
  endtask

  initial begin
    logic [31:0] lhs, rhs;
    integer seed;
    seed=32'h5616a32b;
    seed=$urandom(seed);
    for (integer index=0; index<8; index++) sample(0,0,1);
    for (integer pattern=0; pattern<8; pattern++) begin
      for (integer bit_index=0; bit_index<64; bit_index++) begin
        for (integer unknown_kind=0; unknown_kind<2; unknown_kind++) begin
          lhs=pattern[0] ? 32'hffff_ffff : pattern[1] ? 32'h8000_0000 : 32'h5555_aaaa;
          rhs=pattern[2] ? 32'h7fff_ffff : 32'haaaa_5555;
          if (bit_index<32) lhs[bit_index]=unknown_kind ? 1'bz : 1'bx;
          else rhs[bit_index-32]=unknown_kind ? 1'bz : 1'bx;
          sample(lhs,rhs,1);
          sample(~lhs,~rhs,0);
          sample(0,32'hffff_ffff,1);
        end
      end
    end
    for (integer index=0; index<20000; index++) begin
      lhs=$urandom;
      rhs=$urandom;
      if (index%7==0) lhs[index%32]=1'bx;
      if (index%11==0) rhs[(index/3)%32]=1'bz;
      sample(lhs,rhs,index%5!=0);
    end
    sample('x,'z,1);
    sample('0,'1,1'bx);
    sample('1,'0,1'bz);
    for (integer index=0; index<8; index++) sample(0,0,1);
    $display("SCALAR_FOUR_STATE_PASS samples=%0d checks=%0d",samples,checks);
    $finish;
  end
endmodule
