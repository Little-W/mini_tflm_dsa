// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 旁路填充与普通标签命中共享缺失请求的状态和快照资格。
module conv_cache_demand_hit #(
  parameter int p_ways = 2
) (
  input wire logic i_bypass /* 启用缓存旁路 */, i_miss /* 前台处于缺失处理状态 */, i_filled /* 缺失请求已经填充 */, i_ready /* 当前请求查询就绪 */ , // 启用缓存旁路；前台处于缺失处理状态；缺失请求已经填充；当前请求查询就绪
  input wire logic [p_ways-1:0] i_hits, // 各缓存路命中结果
  output logic o_hit // 当前缓存路或请求命中
);
  assign o_hit = i_miss && i_ready && (i_bypass ? i_filled : (|i_hits));
endmodule

`default_nettype wire
