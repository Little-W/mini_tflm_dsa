// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 将九位模加拆为三个三位分组，分别准备进位候选并选择最终结果。
module conv_im2col_sample_sum(
  input wire logic [8:0] i_a, // 差值或和值的第一操作数
  input wire logic [8:0] i_b, // 差值或和值的第二操作数
  output logic [8:0] o_sum // 完整宽度的模加结果
);
  logic [2:0][2:0] zero_value, one_value;
  logic [2:0] generate_value, propagate_value;
  logic high_carry;
  for (genvar part=0; part<3; part++) begin:g_part
    conv_im2col_sample_sum_group u_part(.i_a(i_a[3*part+:3]), .i_b(i_b[3*part+:3]),
      .o_zero(zero_value[part]), .o_one(one_value[part]),
      .o_generate(generate_value[part]), .o_propagate(propagate_value[part]));
  end
  conv_im2col_sample_sum_carry u_carry(.i_g0(generate_value[0]), .i_g1(generate_value[1]),
    .i_p1(propagate_value[1]), .o_carry(high_carry));
  assign o_sum[2:0]=zero_value[0];
  conv_im2col_sample_sum_select u_middle(.i_zero(zero_value[1]),.i_one(one_value[1]),
    .i_carry(generate_value[0]),.o_sum(o_sum[5:3]));
  conv_im2col_sample_sum_select u_high(.i_zero(zero_value[2]),.i_one(one_value[2]),
    .i_carry(high_carry),.o_sum(o_sum[8:6]));
endmodule

`default_nettype wire
