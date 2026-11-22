// SPDX-License-Identifier: Apache-2.0
// 坐标参考函数使用完整定宽加法、行边界比较与过程选择优先次序。
`default_nettype none
module prefetch_coordinate_reference(
 input conv_im2col_pkg::conv_cfg_t i_c,
 input logic signed [34:0] accepted_coordinate_q [2],
 input logic [31:0] pf_step_q,prefetch_wrap_base_q,
 input logic [31:0] pf_y_base_q,pf_y_wrapped_q,pf_kernel_advance_q,
 input logic pf_window_ahead_q,
 input logic signed [32:0] pf_window_dx_q,pf_fragment_dx_q,
 input logic [16:0] pf_window_dy_q,
 input logic [31:0] tile_extent_q [2],
 output logic [31:0] pf_x,pf_y,
 output logic signed [34:0] complete_sum,
 output logic crosses_row
);

 localparam integer p_coord_w=35;
 logic [31:0] prefetch_next_x,prefetch_wrapped_x;
 logic [1:0] unused_prefetch_x_carry;
 logic pf_stream_lookahead;
 logic signed [34:0] pf_horizontal_delta,pf_horizontal_sum,pf_wrap_x,pf_window_x,pf_window_y;
 logic [34:0] prefetch_horizontal_sum;
 logic unused_prefetch_horizontal_carry;
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_x (
    .i_a(32'(accepted_coordinate_q[0])), .i_b(pf_step_q), .i_carry(1'b0),
    .o_sum(prefetch_next_x), .o_carry(unused_prefetch_x_carry[0])
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_wrapped_x (
    .i_a(prefetch_wrap_base_q), .i_b(pf_step_q), .i_carry(1'b0),
    .o_sum(prefetch_wrapped_x), .o_carry(unused_prefetch_x_carry[1])
  );

  assign pf_horizontal_delta = pf_window_ahead_q ?
      $signed(p_coord_w'(pf_window_dx_q)) : $signed(p_coord_w'(pf_fragment_dx_q));

  parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_horizontal (
    .i_a(accepted_coordinate_q[0]), .i_b(pf_horizontal_delta), .i_carry(1'b0),
    .o_sum(prefetch_horizontal_sum), .o_carry(unused_prefetch_horizontal_carry)
  );
`ifdef SYNTHESIS
  assign pf_horizontal_sum = $signed(prefetch_horizontal_sum);
`else
  always_comb begin
    case (^{accepted_coordinate_q[0], pf_horizontal_delta})
      1'b0, 1'b1: pf_horizontal_sum = $signed(prefetch_horizontal_sum);
      default: pf_horizontal_sum = accepted_coordinate_q[0] + pf_horizontal_delta;
    endcase
  end
`endif
  assign pf_stream_lookahead = i_c.windowed && i_c.input_c >= 16'd16;
  always_comb begin
    pf_x=prefetch_next_x;pf_y=pf_y_base_q;
    if (pf_x>=32'(i_c.input_w)) begin
      // 跨越输入行时保留横向余量，并预测下一输出行使用的同一核位置。
      pf_x=pf_stream_lookahead ? prefetch_wrapped_x : 32'd0;
      pf_y=pf_y_wrapped_q;
    end
    // 小通道片段按核行预测，换核行时保存相应的输入横坐标。
    pf_wrap_x=pf_horizontal_sum;
    if (!pf_stream_lookahead && i_c.windowed && tile_extent_q[0]==1 && tile_extent_q[1]<=32'(i_c.group_c) &&
        i_c.kernel_w>1 && i_c.kernel_h>1 && i_c.dilation_w==1 && i_c.dilation_h==1 &&
        pf_kernel_advance_q>=32'(i_c.kernel_w) &&
        pf_kernel_advance_q<2*32'(i_c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(accepted_coordinate_q[1])+1;
    end
    // 小通道的跨步窗口预测后续两个输出位置，字偏移决定预测距离。

    pf_window_x=pf_horizontal_sum;
    pf_window_y=accepted_coordinate_q[1]+$signed(p_coord_w'(pf_window_dy_q));
    if(pf_window_ahead_q) begin pf_x=32'(pf_window_x);pf_y=32'(pf_window_y);end
  end
 assign complete_sum=pf_horizontal_sum;
 assign crosses_row=(prefetch_next_x>=32'(i_c.input_w));
endmodule
`default_nettype none
