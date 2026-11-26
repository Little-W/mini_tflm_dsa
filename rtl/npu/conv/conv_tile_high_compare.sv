// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两位差值在两种借位条件下分别比较，所有输出均只依赖六个位输入。
module conv_tile_high_compare #(
  parameter bit p_borrow = 1'b0
) (
  input wire logic [1:0] i_a, // 差值或和值的第一操作数
  input wire logic [1:0] i_b, // 差值或和值的第二操作数
  input wire logic [1:0] i_target, // 差值的比较目标
  output logic o_less, // 差值小于比较目标
  output logic o_equal, // 差值等于比较目标
  output logic o_borrow, // 减法产生借位
  output logic o_top // 差值的最高位
);
  logic [1:0] difference;
  logic [2:0] borrow;
  assign borrow[0] = p_borrow;
  for (genvar bit_index = 0; bit_index < 2; bit_index++) begin : g_bit
    assign difference[bit_index] = i_a[bit_index] ^ i_b[bit_index] ^ borrow[bit_index];
    assign borrow[bit_index+1] = (!i_a[bit_index] && i_b[bit_index]) ||
        (!(i_a[bit_index] ^ i_b[bit_index]) && borrow[bit_index]);
  end
  assign o_less = (!difference[1] && i_target[1]) ||
      (!(difference[1] ^ i_target[1]) && !difference[0] && i_target[0]);
  assign o_equal = !(|(difference ^ i_target));
  assign o_borrow = borrow[2];
  assign o_top = difference[1];
endmodule

`default_nettype wire
