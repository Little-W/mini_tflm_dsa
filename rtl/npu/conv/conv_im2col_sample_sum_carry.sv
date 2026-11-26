// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 合并前两个三位分组的进位产生与传播条件，形成第三组的输入进位。
module conv_im2col_sample_sum_carry(
  input wire logic i_g0, // 第一组三位产生的进位
  input wire logic i_g1, // 第二组三位产生的进位
  input wire logic i_p1, // 第二组三位传播输入进位
  output logic o_carry // 送入第三组三位的进位
);
  assign o_carry = i_g1 | (i_p1 & i_g0);
endmodule

`default_nettype wire
