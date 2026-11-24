// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 十六位长度的模坐标区间最多经过两个高位分段，端点各自完成范围比较。
(* keep_hierarchy = "yes" *)
module conv_coordinate_range #(
  parameter int p_width = 35
) (
  input wire logic [p_width-1:0] i_base,
  input wire logic [p_width-1:0] i_lower,
  input wire logic [p_width-1:0] i_upper,
  input wire logic i_block_cross,
  output logic o_valid
);
  logic lower_equal, upper_equal;
  logic lower_before, upper_before;

  assign lower_equal = i_base[p_width-1:16] == i_lower[p_width-1:16];
  assign upper_equal = i_base[p_width-1:16] == i_upper[p_width-1:16];
  assign lower_before = i_base[15:0] < i_lower[15:0];
  assign upper_before = i_base[15:0] < i_upper[15:0];
  assign o_valid = i_block_cross ?
      ((lower_equal && !lower_before) || (upper_equal && upper_before)) :
      (lower_equal && !lower_before && upper_before);
endmodule

`default_nettype wire
