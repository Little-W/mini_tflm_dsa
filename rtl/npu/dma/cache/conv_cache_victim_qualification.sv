// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 地址和运行条件提前准备，替换路命中只参与最终冲突资格。
module conv_cache_victim_qualification #(
  parameter int p_ways = 2
) (
  input wire logic i_demand_eligible /* 缺失请求可更新元数据 */, i_bypass_eligible /* 旁路填充可更新元数据 */ , // 缺失请求可更新元数据；旁路填充可更新元数据
  input wire logic [p_ways-1:0] i_selected_hits, // 被选缓存路命中结果
  output logic o_conflict // 当前读取存在写入冲突
);
  assign o_conflict = i_bypass_eligible || (i_demand_eligible && (|i_selected_hits));
endmodule

`default_nettype wire
