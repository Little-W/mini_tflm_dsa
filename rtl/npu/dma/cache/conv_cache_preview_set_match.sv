// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行比较正式请求的哈希组号与窗口索引，末级选择预读快照的组号匹配结果。
// 两位哈希比较直接归并异或关系，窗口模式控制只参与单比特来源选择。
(* keep_hierarchy = "yes" *)
module conv_cache_preview_set_match #(
  parameter int p_set_width = 4,
  parameter int p_line_shift = 7
) (
  input logic [31:0] i_request_address, // 正式请求的完整字节地址
  input logic [31:0] i_request_index, // 正式请求的窗口索引
  input logic i_windowed, // 当前配置启用窗口索引
  input logic i_index_valid, // 正式请求提供有效的窗口索引
  input logic [p_set_width-1:0] i_saved_set, // 预读快照保存的缓存组号
  output logic o_match // 当前请求的组号与预读快照相同
);
  //! 0. 分组匹配信号
  //! ----------------

  localparam int p_groups = (p_set_width + 1) / 2;
  logic [p_set_width-1:0] address_low;
  logic [p_set_width-1:0] address_high;
  (* keep = 1 *) logic [p_groups-1:0] hashed_match;
  (* keep = 1 *) logic [p_groups-1:0] indexed_match;

  //! 1. 并行比较两类组号
  //! --------------------

  assign address_low = p_set_width'(i_request_address >> p_line_shift);
  assign address_high = p_set_width'(i_request_address >> (p_line_shift + p_set_width));
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_low = group_index * 2;
    localparam int p_bits = p_set_width-p_low < 2 ? p_set_width-p_low : 2;
    assign hashed_match[group_index] =
        (address_low[p_low+:p_bits] ^ address_high[p_low+:p_bits]) == i_saved_set[p_low+:p_bits];
    assign indexed_match[group_index] =
        i_request_index[p_low+:p_bits] == i_saved_set[p_low+:p_bits];
  end

  //! 2. 末级选择匹配结果
  //! --------------------

  always_comb begin
    if (i_windowed && i_index_valid) o_match = &indexed_match;
    else o_match = &hashed_match;
  end
endmodule

`default_nettype wire
