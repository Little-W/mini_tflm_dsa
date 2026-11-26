// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 正常读取和复位读取均使用预先计算的比较值，来源控制只经过一层布尔选择。
module conv_cache_offer_match_select #(
  parameter bit p_capture_matches = 1'b1
) (
  input wire logic rst_n, // 低有效复位
  input wire logic i_capture /* 本周期保存候选字段 */, i_current_match /* 当前字段的地址匹配结果 */ , // 本周期保存候选字段；当前字段的地址匹配结果
  input wire logic i_reset_captured_match /* 复位期间新字段的匹配结果 */, i_reset_held_match /* 复位期间保存字段的匹配结果 */ , // 复位期间新字段的匹配结果；复位期间保存字段的匹配结果
  output logic o_match // 所选字段匹配结果
);
  assign o_match = rst_n ?
      ((i_capture == p_capture_matches) || i_current_match) :
      (i_capture ? i_reset_captured_match : i_reset_held_match);
endmodule

`default_nettype wire
