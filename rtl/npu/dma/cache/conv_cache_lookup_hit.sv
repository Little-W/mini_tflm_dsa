// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 缺失请求和工作请求分别形成命中结果，工作快照只参与末级归并。
module conv_cache_lookup_hit #(
  parameter int p_ways = 2
) (
  input wire logic i_bypass /* 启用缓存旁路 */, i_miss /* 前台处于缺失处理状态 */, i_filled /* 缺失请求已经填充 */, i_demand_ready /* 缺失请求查询就绪 */, i_work_ready /* 工作请求查询就绪 */ , // 启用缓存旁路；前台处于缺失处理状态；缺失请求已经填充；缺失请求查询就绪；工作请求查询就绪
  input wire logic [p_ways-1:0] i_demand_hits /* 缺失请求各路命中结果 */, i_work_hits /* 工作请求各路命中结果 */ , // 缺失请求各路命中结果；工作请求各路命中结果
  output logic o_hit // 当前缓存路或请求命中
);
  logic demand_eligible, work_eligible, parallel_hit;
  conv_cache_lookup_qualifier #(.p_ways(p_ways)) u_qualifier (
    .i_bypass(i_bypass), .i_miss(i_miss), .i_filled(i_filled),
    .i_demand_hits(i_demand_hits), .i_work_hits(i_work_hits),
    .o_demand_eligible(demand_eligible), .o_work_eligible(work_eligible)
  );
  assign parallel_hit = (i_demand_ready && demand_eligible) ||
      (i_work_ready && work_eligible);
  always_comb begin
    o_hit = parallel_hit;
`ifndef SYNTHESIS
    if ((^i_bypass) === 1'bx)
      o_hit = i_bypass ? i_filled && i_miss && i_demand_ready :
          ((i_miss && i_demand_ready && (|i_demand_hits)) ||
           (!i_miss && i_work_ready && (|i_work_hits)));
`endif
  end
endmodule

`default_nettype wire
