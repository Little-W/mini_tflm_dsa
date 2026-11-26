// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 合并位置高段、低段和进位关系，检查描述符覆盖的全部行是否有效。
module conv_descriptor_row_range_result (
  input logic i_high_before, // 位置高段小于上限高段
  input logic i_high_equal, // 位置高段等于上限高段
  input logic i_high_last, // 位置高段加一后等于上限高段
  input logic i_low_carry, // 位置低段和行数相加的进位
  input logic i_low_within, // 位置低段终点未超过上限低段
  output logic o_within // 描述符全部行处于位置范围内
);
  assign o_within =
      (i_high_before && (!i_low_carry || !i_high_last || i_low_within)) ||
      (i_high_equal && !i_low_carry && i_low_within);
endmodule

`default_nettype wire
