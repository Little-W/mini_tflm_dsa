// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 容量资格提前形成，字地址匹配只参与最终请求接收条件。
module conv_cache_request_qualification (
  input wire logic i_available /* 当前请求容量可用 */, i_bypass /* 启用缓存旁路 */, i_snapshot_valid /* 查询快照有效 */, i_snapshot_match /* 查询快照与请求匹配 */ , // 当前请求容量可用；启用缓存旁路；查询快照有效；查询快照与请求匹配
  output logic o_fire // 当前请求可消费
);
  assign o_fire = i_available && (i_bypass || (i_snapshot_valid && i_snapshot_match));
endmodule

`default_nettype wire
