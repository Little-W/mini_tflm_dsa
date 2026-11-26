// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 标签与有效位独立完成读取，命中资格只合并运行和填充状态。
(* keep_hierarchy = "yes" *)
module conv_cache_tag_qualification (
  input wire logic i_cache_active /* 缓存已配置且有效位清除完成 */, i_valid /* 当前查询有效 */, i_tag_match /* 当前查询标签匹配 */ , // 缓存已配置且有效位清除完成；当前查询有效；当前查询标签匹配
  input wire logic i_fill_active /* 填充传输正在进行 */, i_fill_selected /* 当前缓存路承担填充 */, i_fill_set_match /* 当前查询组号与填充组号匹配 */ , // 填充传输正在进行；当前缓存路承担填充；当前查询组号与填充组号匹配
  output logic o_hit // 当前缓存路或请求命中
);
  assign o_hit = i_cache_active && i_valid && i_tag_match &&
      !(i_fill_active && i_fill_selected && i_fill_set_match);
endmodule

`default_nettype wire
