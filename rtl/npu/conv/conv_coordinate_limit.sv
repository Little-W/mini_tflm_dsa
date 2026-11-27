// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查坐标高位和十六位尺寸范围，输出零起点有效区间的包含关系。
(* keep_hierarchy = "yes" *)
module conv_coordinate_limit #(
  parameter int unsigned p_width = 35
) (
  input wire logic [p_width-1:0] i_coordinate, // 需要检查的完整定宽坐标
  input wire logic [15:0] i_limit, // 有效坐标区间的不包含上界
  output logic o_valid // 坐标位于零到尺寸之间
);
  logic low_before, unused_equal;
  parallel_unsigned_compare #(.p_width(16), .p_preserve_groups(1'b1)) u_low (
    .i_a(i_coordinate[15:0]), .i_b(i_limit), .o_less(low_before), .o_equal(unused_equal)
  );
  assign o_valid = !(|i_coordinate[p_width-1:16]) && low_before;
endmodule

`default_nettype wire
