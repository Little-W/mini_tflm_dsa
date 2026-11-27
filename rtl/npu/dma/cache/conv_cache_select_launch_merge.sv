// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 早到资格已经包含请求种类，两个分支在五个输入的末级表达式中同时归并。
(* keep_hierarchy = "yes" *)
module conv_cache_select_launch_merge (
  input wire logic i_prefetch_ready, // 预取早到资格
  input wire logic i_demand_ready, // 需求早到资格
  input wire logic i_fire, // 本周期消费工作请求
  input wire logic i_set_match, // 工作请求使用当前替换组
  input wire logic i_hit, // 当前工作请求命中缓存
  output logic o_launch // 至少一个替换分支允许发送
);
  assign o_launch = (i_prefetch_ready && !(i_fire && (i_set_match || !i_hit))) ||
      (i_demand_ready && !(i_fire && i_set_match));
endmodule

`default_nettype wire
