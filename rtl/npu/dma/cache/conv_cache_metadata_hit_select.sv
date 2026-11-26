// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 工作请求和缺失请求分别选择优先命中路，元数据写入资格在末级归并。
module conv_cache_metadata_hit_select #(
  parameter int p_ways = 2,
  parameter int p_selected_way = 0
) (
  input wire logic i_work_eligible /* 工作请求可更新元数据 */, i_demand_eligible /* 缺失请求可更新元数据 */, i_bypass_eligible /* 旁路填充可更新元数据 */ , // 工作请求可更新元数据；缺失请求可更新元数据；旁路填充可更新元数据
  input wire logic [p_ways-1:0] i_work_hits /* 工作请求各路命中结果 */, i_demand_hits /* 缺失请求各路命中结果 */ , // 工作请求各路命中结果；缺失请求各路命中结果
  output logic o_hit // 当前缓存路或请求命中
);
  logic work_selected, demand_selected;
  if (p_selected_way == p_ways-1) begin : g_last
    assign work_selected = i_work_hits[p_selected_way];
    assign demand_selected = i_demand_hits[p_selected_way];
  end else begin : g_lower
    assign work_selected = i_work_hits[p_selected_way] && !(|i_work_hits[p_ways-1:p_selected_way+1]);
    assign demand_selected = i_demand_hits[p_selected_way] && !(|i_demand_hits[p_ways-1:p_selected_way+1]);
  end
  conv_cache_metadata_hit_finish u_finish (
    .i_bypass_eligible(i_bypass_eligible), .i_work_eligible(i_work_eligible),
    .i_demand_eligible(i_demand_eligible), .i_work_selected(work_selected),
    .i_demand_selected(demand_selected), .o_hit(o_hit)
  );
endmodule

`default_nettype wire
