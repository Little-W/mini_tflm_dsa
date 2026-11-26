// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 工作请求与缺失请求的优先命中位先行形成，写入资格只进行单比特归并。
module conv_cache_metadata_hit_finish (
  input wire logic i_bypass_eligible /* 旁路填充可更新元数据 */, i_work_eligible /* 工作请求可更新元数据 */, i_demand_eligible /* 缺失请求可更新元数据 */ , // 旁路填充可更新元数据；工作请求可更新元数据；缺失请求可更新元数据
  input wire logic i_work_selected /* 工作请求选中当前缓存路 */, i_demand_selected /* 缺失请求选中当前缓存路 */ , // 工作请求选中当前缓存路；缺失请求选中当前缓存路
  output logic o_hit // 当前缓存路或请求命中
);
  assign o_hit = i_bypass_eligible ||
      (i_work_eligible && i_work_selected) || (i_demand_eligible && i_demand_selected);
endmodule

`default_nettype wire
