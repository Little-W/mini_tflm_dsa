// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps
module tb_numeric;
  logic clk = 1'b0;
  logic enable = 1'b0;
  logic signed [31:0] operand_a = '0;
  logic signed [31:0] operand_b = '0;
  wire signed [63:0] product [2];
  logic signed [63:0] expected [3];
  logic signed [31:0] directed [14];
  integer accepted = 0;
  integer samples = 0;
  integer checks [2];
  integer hold_checks [2];

  for (genvar configuration=0; configuration<2; configuration++) begin : g_configuration
    registered_multiplier_s32 #(
      .p_input_register(configuration != 0),
      .p_b_input_register(configuration != 0)
    ) u_multiplier (
      .clk(clk), .i_en(enable), .i_a(operand_a), .i_b(operand_b),
      .o_product(product[configuration])
    );
  end

  // 独立有符号整数参考按实际使能边沿推进，并逐周期检查暂停保持。
  task automatic sample(input logic signed [31:0] lhs, rhs, input logic enabled);
    logic signed [63:0] lhs_extended, rhs_extended;
    operand_a = lhs;
    operand_b = rhs;
    enable = enabled;
    lhs_extended = {{32{lhs[31]}}, lhs};
    rhs_extended = {{32{rhs[31]}}, rhs};
    clk = 1'b0;
    #1;
    clk = 1'b1;
    if (enabled) begin
      expected[2] = expected[1];
      expected[1] = expected[0];
      expected[0] = lhs_extended * rhs_extended;
      accepted++;
    end
    #1;
    for (integer configuration=0; configuration<2; configuration++) begin
      if (accepted >= configuration+2) begin
        if (product[configuration] !== expected[configuration+1])
          $fatal(1, "完整乘积或周期不同 config=%0d sample=%0d actual=%h expected=%h",
              configuration, samples, product[configuration], expected[configuration+1]);
        checks[configuration]++;
        if (!enabled) hold_checks[configuration]++;
      end
    end
    samples++;
    clk = 1'b0;
    #1;
  endtask

  initial begin
    integer seed;
    seed = 32'h25d17a9c;
    seed = $urandom(seed);
    for (integer index=0; index<3; index++) expected[index]='0;
    for (integer index=0; index<2; index++) begin
      checks[index]=0;
      hold_checks[index]=0;
    end
    directed[0]=32'sh80000000;
    directed[1]=32'sh7fffffff;
    directed[2]=-32'sd1;
    directed[3]=32'sd0;
    directed[4]=32'sd1;
    directed[5]=32'sh0000ffff;
    directed[6]=32'shffff0000;
    directed[7]=32'sh00010000;
    directed[8]=32'sh8000ffff;
    directed[9]=32'sh7fff0001;
    directed[10]=32'sh5555aaaa;
    directed[11]=32'shaaaa5555;
    directed[12]=32'sh00008000;
    directed[13]=32'shffff8000;
    for (integer lhs=0; lhs<14; lhs++)
      for (integer rhs=0; rhs<14; rhs++) sample(directed[lhs], directed[rhs], 1'b1);
    for (integer bit_index=0; bit_index<32; bit_index++) begin
      for (integer other_bit=0; other_bit<32; other_bit++) begin
        sample(32'd1<<bit_index, 32'd1<<other_bit, 1'b1);
        sample(~(32'd1<<bit_index), 32'd1<<other_bit, 1'b1);
        sample(32'd1<<bit_index, ~(32'd1<<other_bit), 1'b1);
      end
    end
    for (integer low_half=0; low_half<65536; low_half++) begin
      sample({16'h7fff,16'(low_half)}, 32'sh8000ffff, 1'b1);
      sample({16'h8000,16'(low_half)}, 32'sh7fffffff, 1'b1);
    end
    for (integer cycle=0; cycle<1000000; cycle++)
      sample(32'($urandom), 32'($urandom), cycle%5 != 0);
    for (integer cycle=0; cycle<3; cycle++) sample(0, 0, 1'b1);
    $display("MULTIPLIER_NUMERIC_PASS samples=%0d accepted=%0d checks_0=%0d checks_1=%0d holds_0=%0d holds_1=%0d latency_0=2 latency_1=3 initiation_interval=1",
        samples, accepted, checks[0], checks[1], hold_checks[0], hold_checks[1]);
    $finish;
  end
endmodule
