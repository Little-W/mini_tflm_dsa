// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按每组三路形成通道范围候选，再并行归并完整通道范围。
(* keep_hierarchy = "yes" *)
module conv_group_range_select #(
  parameter int unsigned p_choices = 8,
  parameter int unsigned p_width = 9
) (
  input wire logic [p_choices-1:0] i_select, // 各通道范围候选的选择条件
  input wire logic [p_choices-1:0][p_width-1:0] i_data, // 各候选的完整通道范围
  output logic [p_width-1:0] o_data // 已选择的通道范围
);
  localparam int p_groups = (p_choices + 2) / 3;
  (* keep = "true" *) logic [p_width-1:0][p_groups-1:0] group_data;
  for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_first = group_index * 3;
      localparam int p_count = p_choices - p_first < 3 ? p_choices - p_first : 3;
      logic [p_count-1:0] selected_data;
      for (genvar item = 0; item < p_count; item++) begin : g_item
        assign selected_data[item] = i_select[p_first+item] && i_data[p_first+item][bit_index];
      end
      // 保留各组三路与或结果，使完整选择只增加一次归并。
      assign group_data[bit_index][group_index] = |selected_data;
    end
    assign o_data[bit_index] = |group_data[bit_index];
  end
endmodule

`default_nettype wire
