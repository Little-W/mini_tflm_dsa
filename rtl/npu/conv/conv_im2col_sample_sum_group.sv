// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每组三位同时形成两种进位输入对应的和值。
module conv_im2col_sample_sum_group(
  input wire logic [2:0] i_a, // 差值或和值的第一操作数
  input wire logic [2:0] i_b, // 差值或和值的第二操作数
  output logic [2:0] o_zero, // 输入进位为零时的三位和值
  output logic [2:0] o_one, // 输入进位为一时的三位和值
  output logic o_generate, // 当前三位产生高段进位
  output logic o_propagate // 当前三位传播输入进位
);
  assign o_zero[0] = i_a[0] ^ i_b[0];
  assign o_zero[1] = i_a[1] ^ i_b[1] ^ (i_a[0] & i_b[0]);
  assign o_zero[2] = i_a[2] ^ i_b[2] ^
      ((i_a[1] & i_b[1]) | ((i_a[1] | i_b[1]) & i_a[0] & i_b[0]));
  assign o_one[0] = ~(i_a[0] ^ i_b[0]);
  assign o_one[1] = i_a[1] ^ i_b[1] ^ (i_a[0] | i_b[0]);
  assign o_one[2] = i_a[2] ^ i_b[2] ^
      ((i_a[1] & i_b[1]) | ((i_a[1] | i_b[1]) & (i_a[0] | i_b[0])));
  assign o_generate = (i_a[2] & i_b[2]) |
      ((i_a[2] | i_b[2]) & i_a[1] & i_b[1]) |
      ((i_a[2] | i_b[2]) & (i_a[1] | i_b[1]) & i_a[0] & i_b[0]);
  assign o_propagate = &(i_a | i_b);
endmodule

`default_nettype wire
