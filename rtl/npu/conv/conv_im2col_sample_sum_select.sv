// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 根据输入进位选择当前三位分组的候选和值。
module conv_im2col_sample_sum_select(
  input wire logic [2:0] i_zero, // 输入进位为零时的三位和值
  input wire logic [2:0] i_one, // 输入进位为一时的三位和值
  input wire logic i_carry, // 当前三位的输入进位
  output logic [2:0] o_sum // 完整宽度的模加结果
);
  assign o_sum = i_carry ? i_one : i_zero;
endmodule

`default_nettype wire
