// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 使用共用高位条件和短低位比较，确定一个固定通道是否处于剩余范围内。
(* keep_hierarchy = "yes" *)
module conv_group_lane_range #(
  parameter int unsigned p_width = 4,
  parameter int unsigned p_lane = 0
) (
  input wire logic i_high_nonzero, // 完整剩余数量的高位部分非零
  input wire logic [p_width-1:0] i_remaining, // 完整剩余数量的低位部分
  output logic o_allowed // 指定通道位于完整剩余范围内
);
  assign o_allowed = i_high_nonzero || p_width'(p_lane) < i_remaining;
endmodule

`default_nettype wire
