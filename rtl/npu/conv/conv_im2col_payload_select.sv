// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 选择当前操作的卷积核列和通道组地址，描述符来源在同一组候选中并行归并。
module conv_im2col_payload_select #(
  parameter bit p_register_descriptor = 1'b0
) (
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前前端运行状态。
  input wire logic i_descriptor, // 当前操作选用描述符准备数据。
  input wire logic [9:0] i_select, // 十个描述符来源的选择位。
  input wire logic [9:0][15:0] i_kernel_candidate, // 十个描述符来源的卷积核列候选。
  input wire logic [9:0][31:0] i_group_candidate, // 十个描述符来源的通道组地址候选。
  input wire logic [15:0] i_saved_kernel_column, // 已准备描述符的卷积核列。
  input wire logic i_chunk_end, // 当前传输到达输出行末。
  input wire logic i_kernel_shape_valid, // 卷积核宽度支持位移解码。
  input wire logic [15:0] i_decoded_kernel_column, // 按配置掩码得到的卷积核列。
  input wire logic [5:0] i_kernel_decode, // 三列卷积核的行列解码结果。
  input wire logic [31:0] i_decode_inner, // 通用除法解码得到的余数。
  input wire logic [31:0] i_initial_kernel_column, // 分块初始卷积核列。
  input wire logic [31:0] i_kernel_column, // 当前卷积核列。
  input wire logic i_tap_wrap, // 卷积核位置沿列推进时换行。
  input wire logic [31:0] i_group_base, // 当前输入像素的通道组起始地址。
  input wire logic [31:0] i_next_row_group, // 下一输出行的通道组地址。
  input wire logic [31:0] i_next_tap_address, // 下一卷积核位置的输入地址。
  input wire logic [1:0][31:0] i_group_reference, // 运行阶段选择的当前核位置和行起点地址。
  output logic [15:0] o_kernel_column, // 当前操作需要保存的卷积核列。
  output logic [1:0][31:0] o_group // 当前核位置和行起点需要保存的通道组地址。
);
  import conv_im2col_frontend_pkg::*;
  logic [15:0] kernel_column_reference;

  // 卷积核列数据按运行阶段预选，各保存条件仅控制寄存器写入。
  always_comb begin
    kernel_column_reference = 16'(i_kernel_column + 1);
    if (i_tap_wrap) kernel_column_reference = 16'd0;
    if (i_chunk_end) kernel_column_reference = 16'(i_initial_kernel_column);
    if (i_state[$clog2(K_DECODE)]) begin
      kernel_column_reference = 16'(i_kernel_decode[1:0]);
      if (i_kernel_shape_valid) kernel_column_reference = i_decoded_kernel_column;
    end
    if (i_state[$clog2(K_WAIT)]) kernel_column_reference = 16'(i_decode_inner);
    if (i_descriptor) kernel_column_reference = 16'(i_saved_kernel_column);
  end

  if (!p_register_descriptor) begin : g_parallel_descriptor_payload
    logic [13:0] kernel_select;
    logic [13:0][15:0] kernel_candidate;
    logic [15:0] kernel_selected, decoded_kernel_column;
    logic [12:0] group_select;
    logic [12:0][63:0] group_candidate;
    logic [63:0] group_selected;

    // 描述符和运行来源组成同一组候选，接收资格仅控制已有寄存器的写入。
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming
      assign kernel_select[candidate] = i_descriptor && i_select[candidate];
      assign kernel_candidate[candidate] = i_kernel_candidate[candidate];
      assign group_select[candidate] = i_descriptor && i_select[candidate];
      assign group_candidate[candidate] = {2{i_group_candidate[candidate]}};
    end
    assign kernel_select[10] = !i_descriptor && i_state[$clog2(K_WAIT)];
    assign kernel_select[11] = !i_descriptor && !i_state[$clog2(K_WAIT)] && i_state[$clog2(K_DECODE)];
    assign kernel_select[12] = !i_descriptor && !i_state[$clog2(K_WAIT)] &&
        !i_state[$clog2(K_DECODE)] && i_chunk_end;
    assign kernel_select[13] = !i_descriptor && !i_state[$clog2(K_WAIT)] &&
        !i_state[$clog2(K_DECODE)] && !i_chunk_end;
    assign decoded_kernel_column = i_kernel_shape_valid ? i_decoded_kernel_column : 16'(i_kernel_decode[1:0]);
    assign kernel_candidate[10] = 16'(i_decode_inner);
    assign kernel_candidate[11] = decoded_kernel_column;
    assign kernel_candidate[12] = 16'(i_initial_kernel_column);
    assign kernel_candidate[13] = i_tap_wrap ? 16'd0 : 16'(i_kernel_column + 1);
    onehot_mux #(.p_choices(14), .p_width(16)) u_kernel (
      .i_select(kernel_select), .i_data(kernel_candidate), .o_data(kernel_selected)
    );
    assign group_select[10] = !i_descriptor && i_state[$clog2(ADDRESS_CHANNEL)];
    assign group_select[11] = !i_descriptor && !i_state[$clog2(ADDRESS_CHANNEL)] && i_chunk_end;
    assign group_select[12] = !i_descriptor && !i_state[$clog2(ADDRESS_CHANNEL)] && !i_chunk_end;
    assign group_candidate[10] = {i_group_base, i_group_base};
    assign group_candidate[11] = {i_next_row_group, i_next_row_group};
    assign group_candidate[12] = {i_next_row_group, i_next_tap_address};
    onehot_mux #(.p_choices(13), .p_width(64)) u_group (
      .i_select(group_select), .i_data(group_candidate), .o_data(group_selected)
    );
`ifdef SYNTHESIS
    assign o_kernel_column = kernel_selected;
    assign {o_group[1], o_group[0]} = group_selected;
`else
    // 未知控制或数据保留逐阶段赋值的四态传播。
    always_comb begin
      o_kernel_column = kernel_column_reference;
      o_group[1] = i_group_reference[1];
      o_group[0] = i_group_reference[0];
      case (^{i_descriptor, i_select, i_kernel_candidate,
              i_group_candidate, i_state, i_chunk_end, i_kernel_shape_valid,
              i_decoded_kernel_column, i_kernel_decode, i_decode_inner, i_initial_kernel_column, i_kernel_column, i_tap_wrap,
              i_group_base, i_next_row_group, i_next_tap_address})
        1'b0, 1'b1: begin
          o_kernel_column = kernel_selected;
          {o_group[1], o_group[0]} = group_selected;
        end
        default: begin end
      endcase
    end
`endif
  end else begin : g_saved_descriptor_payload
    assign o_kernel_column = kernel_column_reference;
    assign o_group[1] = i_group_reference[1];
    assign o_group[0] = i_group_reference[0];
  end

endmodule
`default_nettype wire
