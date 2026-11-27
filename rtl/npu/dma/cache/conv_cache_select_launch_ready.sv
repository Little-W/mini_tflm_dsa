// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两类替换请求并行合并早到条件，当前工作请求的接收信号保持在本模块之外。
(* keep_hierarchy = "yes" *)
module conv_cache_select_launch_ready (
  input wire logic i_capacity_ready, // 填充容量与替换快照已就绪
  input wire logic i_victim_conflict, // 当前需求占用待替换缓存路
  input wire logic i_prefetch, // 替换快照属于预取请求
  input wire logic i_prefetch_ready, // 预取地址及查询状态允许发送
  input wire logic i_demand_ready, // 需求地址及查询状态允许发送
  input wire logic i_hint_busy, // 提示查询正在使用当前组元数据
  input wire logic i_hit, // 当前需求命中缓存
  output logic o_prefetch_ready, // 预取早到条件全部满足
  output logic o_demand_ready // 需求早到条件全部满足
);
  assign o_prefetch_ready = i_capacity_ready && !i_victim_conflict && i_prefetch &&
      i_prefetch_ready && !i_hint_busy;
  assign o_demand_ready = i_capacity_ready && !i_victim_conflict && !i_prefetch &&
      i_demand_ready && !i_hit && !i_hint_busy;
endmodule

`default_nettype wire
