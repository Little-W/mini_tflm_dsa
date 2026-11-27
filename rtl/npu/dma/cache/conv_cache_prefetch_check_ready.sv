// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 活动预取与标签快照先合并，填充数据的同组更新使本次查询结果失效。
(* keep_hierarchy = "yes" *)
module conv_cache_prefetch_check_ready (
  input wire logic i_pending, // 当前存在有效的活动预取项
  input wire logic i_lookup_ready, // 预取标签与组号快照就绪
  input wire logic i_fill_busy, // 本周期更新填充元数据
  input wire logic i_fill_set_match, // 填充更新与预取查询使用同一组
  output logic o_eligible // 已有快照满足预取命中检查条件
);
  assign o_eligible = i_pending && i_lookup_ready && !(i_fill_busy && i_fill_set_match);
endmodule

`default_nettype wire
