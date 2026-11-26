// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每个进位归约独立综合，地址位之间不串联组合计算。
module conv_cache_increment_bit #(
  parameter int p_lower_width = 1
) (
  input wire logic i_bit, // 当前地址位
  input wire logic [p_lower_width-1:0] i_lower, // 当前位以下的进位相关位
  output logic o_bit // 递增后的当前地址位
);
  assign o_bit = i_bit ^ (&i_lower);
endmodule

`default_nettype wire
