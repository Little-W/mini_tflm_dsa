// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 比较两个描述符字段，产生供上下文复用资格使用的完整相等条件。
module conv_descriptor_match #(
  parameter int unsigned p_width = 32,
  parameter bit p_preserve_groups = 1'b0,
  parameter int unsigned p_reduce_group_width = 0 // 末级归并每组包含的相等条件数量
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
    if (p_reduce_group_width > 0) begin : g_bounded_reduction
      localparam int p_reduce_groups = (p_groups + p_reduce_group_width - 1) / p_reduce_group_width;
      (* keep = "true" *) logic [p_reduce_groups-1:0] reduce_equal;
      (* keep = "true" *) logic complete_equal;
      for (genvar group_index = 0; group_index < p_reduce_groups; group_index++) begin : g_reduce
        localparam int p_first = group_index * p_reduce_group_width;
        localparam int p_count = p_groups-p_first < p_reduce_group_width ? p_groups-p_first : p_reduce_group_width;
        assign reduce_equal[group_index] = &group_equal[p_first+:p_count];
      end
      assign complete_equal = &reduce_equal;
      assign o_equal = complete_equal;
    end else begin : g_flat_reduction
      assign o_equal = &group_equal;
    end
  end else begin : g_complete_match
    // 描述符资格比较与使用结果的条件共同优化。
    assign o_equal = i_a == i_b;
  end
endmodule

`default_nettype wire
