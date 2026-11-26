// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行比较通道范围的高位部分，提供相等、加一相等和最高高位组标志。
(* keep_hierarchy = "yes" *)
module conv_group_high_compare #(
  parameter int unsigned p_width = 11
) (
  input wire logic [p_width-1:0] i_group, // 配置通道组大小的高位部分
  input wire logic [p_width-1:0] i_channel, // 当前通道坐标的高位部分
  output logic o_equal, // 两个高位部分相等
  output logic o_next_equal, // 通道高位加一后与配置高位相等
  output logic o_last // 通道高位全部为一
);
  localparam int p_groups = (p_width + 5) / 6;
  (* keep = "true" *) logic [p_groups-1:0] last_group;
  conv_descriptor_match #(.p_width(p_width), .p_preserve_groups(1'b1)) u_same (
    .i_a(i_group), .i_b(i_channel), .o_equal(o_equal)
  );
  conv_channel_increment_match #(.p_width(p_width)) u_next (
    .i_a(i_channel), .i_target(i_group), .o_equal(o_next_equal)
  );
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_last
    localparam int p_first = group_index * 6;
    localparam int p_bits = p_width - p_first < 6 ? p_width - p_first : 6;
    assign last_group[group_index] = &i_channel[p_first+:p_bits];
  end
  assign o_last = &last_group;
endmodule

`default_nettype wire
