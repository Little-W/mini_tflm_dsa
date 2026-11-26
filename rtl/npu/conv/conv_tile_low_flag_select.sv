// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 默认十六列只检查余量最高位，显式列数由独立的完整低段比较处理。
module conv_tile_low_flag_select (
  input wire logic [1:0] i_high_borrow, // 两种低段借位条件下的高段借位
  input wire logic [1:0] i_high_top, // 两种低段借位条件下的高段最高位
  input wire logic i_low_borrow, // 低段减法产生借位
  input wire logic i_columns_nonzero, // 输入列数采用显式长度
  output logic o_borrow, // 减法产生借位
  output logic o_default_allows // 默认列数允许本次范围选择
);
  assign o_borrow = i_low_borrow ? i_high_borrow[1] : i_high_borrow[0];
  assign o_default_allows = i_columns_nonzero ||
      (i_low_borrow ? i_high_top[1] : i_high_top[0]);
endmodule

`default_nettype wire
