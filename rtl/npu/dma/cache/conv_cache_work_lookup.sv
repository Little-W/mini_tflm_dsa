// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 旁路和普通查询分别提供匹配条件，有效状态只参与最终读取资格。
module conv_cache_work_lookup (
  input wire logic i_valid /* 当前查询有效 */, i_bypass /* 启用缓存旁路 */, i_set_match /* 查询组号匹配 */, i_word_match /* 查询字地址匹配 */, i_snapshot_match /* 查询快照与请求匹配 */ , // 当前查询有效；启用缓存旁路；查询组号匹配；查询字地址匹配；查询快照与请求匹配
  output logic o_ready // 当前查询结果可使用
);
  assign o_ready = i_valid &&
      (i_bypass ? (i_set_match && i_word_match) : i_snapshot_match);
endmodule

`default_nettype wire
