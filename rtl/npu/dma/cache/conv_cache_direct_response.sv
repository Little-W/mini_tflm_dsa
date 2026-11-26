// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 已完成响应与当前命中并行生成有效位，返回资格只选择最终传输条件。
module conv_cache_direct_response #(
  parameter int p_ways = 2
) (
  input wire logic i_saved_valid /* 已完成响应有效 */, i_hit_eligible /* 当前命中可直接响应 */ , // 已完成响应有效；当前命中可直接响应
  input wire logic [p_ways-1:0] i_hits, // 各缓存路命中结果
  output logic o_valid // 读取或传输有效结果
);
  assign o_valid = i_saved_valid || (i_hit_eligible && (|i_hits));
endmodule

`default_nettype wire
