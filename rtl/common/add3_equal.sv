`default_nettype none

// 三项加法先并行压缩成两个操作数，再检查各位进位与目标值的一致性。
module add3_equal #(
    parameter int unsigned p_width = 32
) (
    input  wire logic [p_width-1:0] i_a /* 第一输入操作数。 */,
    input  wire logic [p_width-1:0] i_b /* 第二输入操作数。 */,
    input  wire logic [p_width-1:0] i_c /* 第三输入操作数。 */,
    input  wire logic [p_width-1:0] i_target /* 待比较的目标值。 */,
    output logic o_equal /* 三个操作数的定宽和等于目标值。 */
);
  logic [p_width-1:0] sum_equal_i_a;
  logic [p_width-1:0] sum_equal_i_b;
  logic [p_width-1:0] sum_equal_i_target;
  logic sum_equal_i_carry_in;
  logic sum_equal_o_equal;
  logic unused_final_carry;

  assign sum_equal_i_a = i_a ^ i_b ^ i_c;
  assign {unused_final_carry, sum_equal_i_b} =
      {(i_a & i_b) | (i_a & i_c) | (i_b & i_c), 1'b0};
  assign sum_equal_i_target = i_target;
  assign sum_equal_i_carry_in = 1'b0;
  assign o_equal = sum_equal_o_equal;

  add_equal #(.p_width(p_width)) u_sum_equal (
      .i_a(sum_equal_i_a), .i_b(sum_equal_i_b), .i_target(sum_equal_i_target),
      .i_carry_in(sum_equal_i_carry_in), .o_equal(sum_equal_o_equal)
  );
endmodule

`default_nettype wire
