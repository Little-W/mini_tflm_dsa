// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个位的模差和借位只依赖六个原始输入位。
module conv_tile_low_difference (
  input wire logic [2:0] i_a, // 差值或和值的第一操作数
  input wire logic [2:0] i_b, // 差值或和值的第二操作数
  output logic [2:0] o_difference, // 低位模减结果
  output logic o_borrow // 减法产生借位
);
  logic [3:0] borrow;
  assign borrow[0] = 1'b0;
  for (genvar bit_index = 0; bit_index < 3; bit_index++) begin : g_bit
    assign o_difference[bit_index] = i_a[bit_index] ^ i_b[bit_index] ^ borrow[bit_index];
    assign borrow[bit_index+1] = (!i_a[bit_index] && i_b[bit_index]) ||
        (!(i_a[bit_index] ^ i_b[bit_index]) && borrow[bit_index]);
  end
  assign o_borrow = borrow[3];
endmodule

`default_nettype wire
