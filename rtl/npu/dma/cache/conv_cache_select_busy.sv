// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 提示占用、请求接收和组号冲突并行计算，候选种类保持各自的阻塞条件。
module conv_cache_select_busy #(
  parameter bit p_prefetch = 1'b1
) (
  input wire logic i_hint_busy /* 提示查询占用候选元数据 */, i_fire /* 本周期消费工作请求 */, i_set_match /* 查询组号匹配 */, i_hit /* 当前请求命中 */ , // 提示查询占用候选元数据；本周期消费工作请求；查询组号匹配；当前请求命中
  output logic o_busy // 候选元数据不可立即使用
);
  if (p_prefetch) begin : g_prefetch
    assign o_busy = i_hint_busy || (i_fire && (i_set_match || !i_hit));
  end else begin : g_demand
    assign o_busy = i_hint_busy || (i_fire && i_set_match);
  end
endmodule

`default_nettype wire
