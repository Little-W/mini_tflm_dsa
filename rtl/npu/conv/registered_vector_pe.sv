// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 操作数在使能边沿进入寄存器，操作码由上层独立寄存并持续控制当前结果。
module registered_vector_pe #(
  parameter bit p_accumulator_preselected = 1'b0
) (
  input wire logic clk,
  input wire logic i_en,
  input wire logic [2:0] i_op,
  input wire logic signed [15:0] i_a,
  input wire logic signed [15:0] i_b,
  input wire logic signed [31:0] i_acc,
  output logic signed [31:0] o_result
);
  // 寄存操作数供乘加和极值比较共同使用。
  logic signed [15:0] operand_a_q, operand_b_q;
  logic signed [31:0] operand_acc_q;

  always_ff @(posedge clk) begin
    if (i_en) begin
      operand_a_q <= i_a;
      operand_b_q <= i_b;
      operand_acc_q <= i_acc;
    end
  end

  vector_pe #(
      .ENABLE_EXTENDED_MULTIPLY(1'b0), .p_accumulator_preselected(p_accumulator_preselected)
  ) u_pe (
    .op(i_op), .a(operand_a_q), .b(operand_b_q),
    .acc(operand_acc_q), .result(o_result)
  );
endmodule

`default_nettype wire
