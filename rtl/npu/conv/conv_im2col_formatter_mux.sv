// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个完整候选在一组内选择，再按六项归并形成最终数据。
module conv_im2col_formatter_mux #(
  parameter int unsigned p_choices = 8,
  parameter int unsigned p_width = 16
)(
  input wire logic [p_choices-1:0] i_select, // 各候选数据的独热选择
  input wire logic [p_choices-1:0][p_width-1:0] i_data, // 等待归并或选择的并行候选数据
  output logic [p_width-1:0] o_data // 完成归并或选择的数据
);
  if (p_choices <= 3) begin : g_leaf
    function automatic logic [p_width-1:0] choose(
      input logic [p_choices-1:0] selected,
      input logic [p_choices-1:0][p_width-1:0] values
    );
      logic [p_width-1:0] result;
      result = '0;
      for (int item = 0; item < p_choices; item++)
        result |= {p_width{selected[item]}} & values[item];
      return result;
    endfunction
    assign o_data = choose(i_select, i_data);
  end else begin : g_groups
    localparam int p_groups = (p_choices+2)/3;
    logic [p_groups-1:0][p_width-1:0] group_value;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_items = p_choices-3*group_index < 3 ? p_choices-3*group_index : 3;
      conv_im2col_formatter_mux #(.p_choices(p_items), .p_width(p_width)) u_group (
        .i_select(i_select[3*group_index+:p_items]), .i_data(i_data[3*group_index+:p_items]),
        .o_data(group_value[group_index])
      );
    end
    conv_im2col_formatter_reduce #(.p_count(p_groups), .p_width(p_width)) u_result (
      .i_data(group_value), .o_data(o_data)
    );
  end
endmodule

`default_nettype wire
