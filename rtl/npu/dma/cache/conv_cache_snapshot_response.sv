// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 响应状态、字地址和范围结果并行归并，保持同步查询后的直接返回。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_response #(
  parameter int p_ways = 2
) (
  input wire logic i_saved_valid /* 已完成响应有效 */, i_control_ready /* 当前状态允许返回响应 */, i_snapshot_match /* 查询快照与请求匹配 */, i_range /* 当前请求位于有效范围 */ , // 已完成响应有效；当前状态允许返回响应；查询快照与请求匹配；当前请求位于有效范围
  input wire logic [p_ways-1:0] i_hits, // 各缓存路命中结果
  output logic o_valid // 读取或传输有效结果
);
  assign o_valid = i_saved_valid ||
      (i_control_ready && i_snapshot_match && i_range && (|i_hits));
endmodule

`default_nettype wire
