// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 预先归并缓存模式与各路标签命中，查询快照就绪信号只参与末级选择。
(* keep_hierarchy = "yes" *)
module conv_cache_lookup_qualifier #(
  parameter int p_ways = 2
) (
  input wire logic i_bypass, // 使用旁路填充结果
  input wire logic i_miss, // 前台处于缺失处理状态
  input wire logic i_filled, // 缺失请求已经填充
  input wire logic [p_ways-1:0] i_demand_hits, // 缺失请求各缓存路标签匹配
  input wire logic [p_ways-1:0] i_work_hits, // 工作请求各缓存路标签匹配
  output logic o_demand_eligible, // 缺失请求满足命中资格
  output logic o_work_eligible // 工作请求满足命中资格
);
  assign o_demand_eligible = i_miss && (i_bypass ? i_filled : (|i_demand_hits));
  assign o_work_eligible = !i_bypass && !i_miss && (|i_work_hits);
endmodule
`default_nettype wire
