// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每条通道的末列资格只使用该通道的范围和运行标志。
module conv_im2col_chunk_lane #(
  parameter bit p_narrow_lane = 1'b1
) (
  input wire logic i_narrow_output, // 输出受总线窄通道范围限制
  input wire logic i_column_allowed, // 当前通道位于有效列范围内
  input wire logic i_next_column_allowed, // 下一通道位于有效列范围内
  input wire logic i_past_active, // 当前输出已经越过有效归约范围
  input wire logic i_group_allowed, // 当前通道位于通道组范围内
  input wire logic i_active_allowed, // 当前通道位于有效归约范围内
  output logic o_end // 当前选择到达范围末尾
);
  assign o_end = (!i_narrow_output || p_narrow_lane) && i_column_allowed && !i_next_column_allowed &&
      (i_past_active || (i_group_allowed && i_active_allowed));
endmodule

`default_nettype wire
