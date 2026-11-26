// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三位相等关系分别形成，完整相等条件独立归并。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_equal #(
  parameter int p_width = 30
) (
  input wire logic [p_width-1:0] i_a /* 比较操作数甲 */, i_b /* 比较操作数乙 */ , // 比较操作数甲；比较操作数乙
  output logic o_equal // 比较操作数相等
);
  localparam int p_groups = (p_width+2)/3;
  // 保留各组三位的相等结果，后级归约只处理每组的一位结果。
  (* keep = 1 *) logic [p_groups-1:0] group_equal;
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_low = group_index*3;
    localparam int p_bits = p_width-p_low < 3 ? p_width-p_low : 3;
    assign group_equal[group_index] = i_a[p_low+:p_bits] == i_b[p_low+:p_bits];
  end
  assign o_equal = &group_equal;
endmodule

`default_nettype wire
