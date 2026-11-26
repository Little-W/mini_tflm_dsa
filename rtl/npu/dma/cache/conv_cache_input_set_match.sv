// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两位哈希组号在同一比较项中形成，索引模式在完整比较后选择。
module conv_cache_input_set_match #(
  parameter int p_set_width = 4,
  parameter int p_line_shift = 7
) (
  input wire logic [31:0] i_address /* 输入字节地址 */, i_index /* 窗口索引 */ , // 输入字节地址；窗口索引
  input wire logic i_indexed, // 使用窗口索引选择组号
  input wire logic [p_set_width-1:0] i_fill_set, // 填充缓存组号
  output logic o_match // 所选字段匹配结果
);
  localparam int p_groups = (p_set_width + 1) / 2;
  logic [p_set_width-1:0] address_low, address_high;
  logic [p_groups-1:0] hashed_matches, indexed_matches;
  assign address_low = p_set_width'(i_address >> p_line_shift);
  assign address_high = p_set_width'(i_address >> (p_line_shift+p_set_width));
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_low = group_index * 2;
    localparam int p_width = p_set_width-p_low < 2 ? p_set_width-p_low : 2;
    assign hashed_matches[group_index] =
        (address_low[p_low+:p_width] ^ address_high[p_low+:p_width]) == i_fill_set[p_low+:p_width];
    assign indexed_matches[group_index] = i_index[p_low+:p_width] == i_fill_set[p_low+:p_width];
  end
  always_comb begin
    if (i_indexed) o_match = &indexed_matches;
    else o_match = &hashed_matches;
  end
endmodule

`default_nettype wire
