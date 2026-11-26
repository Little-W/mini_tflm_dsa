// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 在组号比较完成后，一次归并缺失请求的快照有效、地址匹配和旁路选择。
(* keep_hierarchy = "yes" *)
module conv_cache_demand_lookup (
  input wire logic i_valid, // 已保存的查询快照有效
  input wire logic i_word_match, // 快照地址与缺失请求地址相同
  input wire logic i_bypass, // 选择旁路填充组号
  input wire logic i_demand_set_match, // 普通缺失请求组号匹配
  input wire logic i_fill_set_match, // 旁路填充组号匹配
  output logic o_ready // 当前缺失请求可使用快照
);
  assign o_ready = i_valid && i_word_match &&
      (i_bypass ? i_fill_set_match : i_demand_set_match);
endmodule
`default_nettype wire
