// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 汇总被替换缓存路的命中结果，并结合查询就绪、需求及旁路资格形成冲突条件。
// 地址匹配和运行条件在输入侧准备，模块末级归并各路命中与查询资格。
(* keep_hierarchy = "yes" *)
module conv_cache_victim_qualification #(
  parameter int p_ways = 2
) (
  input logic i_lookup_ready, // 需求查询已完成，可使用当前缓存路命中结果
  input logic i_demand_eligible, // 需求请求具备元数据更新资格
  input logic i_bypass_eligible, // 旁路填充具备元数据更新资格
  input logic [p_ways-1:0] i_selected_hits, // 每一位表示该路命中且被选为替换路
  output logic o_conflict // 当前需求与元数据替换操作发生冲突
);
  //! 0. 归并替换冲突
  //! ----------------

  assign o_conflict = i_lookup_ready &&
      (i_bypass_eligible || (i_demand_eligible && (|i_selected_hits)));
endmodule

`default_nettype wire
