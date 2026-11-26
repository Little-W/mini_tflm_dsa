// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 六个输入以内独立归并，较宽向量按相同规则逐层合并。
module conv_im2col_formatter_reduce #(
  parameter int unsigned p_count = 6,
  parameter int unsigned p_width = 1
)(
  input wire logic [p_count-1:0][p_width-1:0] i_data, // 等待归并或选择的并行候选数据
  output logic [p_width-1:0] o_data // 完成归并或选择的数据
);
  if (p_count <= 6) begin : g_leaf
    function automatic logic [p_width-1:0] combine(input logic [p_count-1:0][p_width-1:0] values);
      logic [p_width-1:0] result;
      result = '0;
      for (int item = 0; item < p_count; item++) result |= values[item];
      return result;
    endfunction
    assign o_data = combine(i_data);
  end else begin : g_groups
    localparam int p_groups = (p_count+5)/6;
    logic [p_groups-1:0][p_width-1:0] group_value;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_items = p_count-6*group_index < 6 ? p_count-6*group_index : 6;
      conv_im2col_formatter_reduce #(.p_count(p_items), .p_width(p_width)) u_group (
        .i_data(i_data[6*group_index+:p_items]), .o_data(group_value[group_index])
      );
    end
    conv_im2col_formatter_reduce #(.p_count(p_groups), .p_width(p_width)) u_result (
      .i_data(group_value), .o_data(o_data)
    );
  end
endmodule

`default_nettype wire
