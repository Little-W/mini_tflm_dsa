// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 比较两个描述符字段，产生供上下文复用资格使用的完整相等条件。
module conv_descriptor_match #(
  parameter int unsigned p_width = 32,
  parameter bit p_preserve_groups = 1'b0
) (
  input logic [p_width-1:0] i_a, // 第一比较字段
  input logic [p_width-1:0] i_b, // 第二比较字段
  output logic o_equal // 两个完整字段相等
);
  if (p_preserve_groups) begin : g_grouped_match
    localparam int p_groups = (p_width + 2) / 3;
    (* keep = "true" *) logic [p_groups-1:0] group_equal;
    // 每组三位独立比较，保留组结果后并行归并完整相等条件。
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_first = group_index * 3;
      localparam int p_bits = p_width - p_first < 3 ? p_width - p_first : 3;
      assign group_equal[group_index] = i_a[p_first+:p_bits] == i_b[p_first+:p_bits];
    end
    assign o_equal = &group_equal;
  end else begin : g_complete_match
    // 描述符资格比较与使用结果的条件共同优化。
    assign o_equal = i_a == i_b;
  end
endmodule

`default_nettype wire
