// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 高段、低段和默认列数资格均已完成，六个位条件直接给出组范围。
module conv_tile_group_range_result (
  input wire logic i_high_before, // 起始通道高段小于组宽高段
  input wire logic i_high_equal, // 起始通道高段等于组宽高段
  input wire logic i_high_next_equal, // 起始通道高段加一后等于组宽高段
  input wire logic i_low_borrow, // 低段减法产生借位
  input wire logic i_low_less, // 低段差值小于输入列数
  input wire logic i_default_allows, // 默认列数允许本次范围选择
  output logic o_fits // 输入分块全部处于通道组范围内
);
  assign o_fits =
      (i_high_before && (!i_low_borrow || !i_high_next_equal || (!i_low_less && i_default_allows))) ||
      (i_high_equal && !i_low_borrow && !i_low_less && i_default_allows);
endmodule

`default_nettype wire
