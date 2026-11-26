// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 高段两种关系和低段比较同时就绪，低位借位只决定最终次序。
module conv_tile_low_less_select (
  input wire logic [1:0] i_high_less, // 两种借位条件下的高段小于标志
  input wire logic [1:0] i_high_equal, // 两种借位条件下的高段相等标志
  input wire logic i_low_borrow, // 低段减法产生借位
  input wire logic i_low_less, // 低段差值小于输入列数
  output logic o_less // 差值小于比较目标
);
  assign o_less = i_low_borrow ?
      (i_high_less[1] || (i_high_equal[1] && i_low_less)) :
      (i_high_less[0] || (i_high_equal[0] && i_low_less));
endmodule

`default_nettype wire
