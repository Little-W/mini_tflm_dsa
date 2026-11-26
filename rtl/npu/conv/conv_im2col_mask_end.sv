// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 输入掩码先形成各个有效长度，再与已经保存的组末位置匹配。
module conv_im2col_mask_end #(
  parameter int p_lanes = 8,
  parameter bit p_contiguous = 1'b0
) (
  input wire logic [p_lanes-1:0] i_available, // 各输出通道的可用掩码
  input wire logic [p_lanes:0] i_boundary, // 各有效长度对应的组末标志
  output logic o_end // 当前选择到达范围末尾
);
  logic [p_lanes:0] selected;
  assign selected[0] = p_contiguous ? !i_available[0] : !(|i_available);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_step
    if (step == p_lanes) begin : g_last
      assign selected[step] = i_available[step-1];
    end else if (p_contiguous) begin : g_contiguous
      assign selected[step] = i_available[step-1] && !i_available[step];
    end else begin : g_general
      assign selected[step] = i_available[step-1] && !(|i_available[p_lanes-1:step]);
    end
  end
  conv_group_range_select #(.p_choices(p_lanes+1), .p_width(1)) u_boundary (
    .i_select(selected), .i_data(i_boundary), .o_data(o_end)
  );
endmodule

`default_nettype wire
