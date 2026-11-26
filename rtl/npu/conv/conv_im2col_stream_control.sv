// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 行、核位置及组内推进分别计算，末级独热选择只接收运行位置条件。
module conv_im2col_stream_control (
  input wire logic i_chunk_end, // 当前输出到达分块末列
  input wire logic i_row_last, // 当前输出处于分块末行
  input wire logic i_row_base_valid, // 当前行起点上下文有效
  input wire logic i_geometry_tile, // 当前分块采用几何计算路径
  input wire logic i_next_row_padding, // 下一行起点需要填充
  input wire logic i_next_row_word_hit, // 下一行起点命中可用的数据字
  input wire logic i_row_coordinate_valid, // 下一行的输入坐标上下文有效
  input wire logic i_past_active, // 当前输出已经越过有效归约范围
  input wire logic i_active_after, // 推进后仍处于有效归约范围
  input wire logic i_group_end, // 当前输出到达通道组末尾
  input wire logic i_coordinate_address_valid, // 当前输入坐标和地址上下文有效
  input wire logic i_next_tap_padding, // 下一卷积核位置需要填充
  input wire logic i_next_word_equal, // 下一位置命中保存的数据字
  input wire logic i_padding, // 当前输入位置需要填充
  input wire logic i_tap_context, // 下一卷积核位置可直接发起读取
  input wire logic i_word_boundary, // 当前推进越过数据字边界
  input wire logic i_stream_eligible, // 流式推进具备读取资格
  output conv_im2col_frontend_pkg::st_t o_state, // 本次输出后采用的运行状态
  output logic o_request_selected, // 选择输出推进读取请求
  output logic o_row_selected, // 选择下一行读取请求
  output logic o_tap_selected // 选择下一卷积核读取请求
);
  import conv_im2col_frontend_pkg::*;
  (* keep = 1 *) st_t row_state, tap_state, column_state;
  logic row_request, tap_request, column_request;
  (* keep = 1 *) logic [3:0] source_select;
  logic [3:0][29:0] candidate;
  logic [29:0] selected;

  always_comb begin
    row_state = FETCH;
    row_request = 1'b0;
    if (i_row_last) row_state = IDLE;
    else if (i_row_base_valid && !i_geometry_tile) begin
      if (i_next_row_padding) row_state = ZERO_STREAM;
      else if (i_next_row_word_hit) row_state = STREAM;
      else row_request = 1'b1;
    end else if (i_row_coordinate_valid) row_state = ADDRESS;
    else row_state = COORD;

    tap_state = FETCH;
    tap_request = 1'b0;
    if (i_coordinate_address_valid) begin
      if (i_next_tap_padding) tap_state = ZERO_STREAM;
      else if (i_next_word_equal && !i_padding) tap_state = STREAM;
      else tap_request = i_tap_context;
    end else tap_state = ADDRESS;

    column_state = FETCH;
    column_request = 1'b0;
    if (i_padding) column_state = ZERO_STREAM;
    else if (!i_word_boundary) column_state = STREAM;
    else column_request = i_stream_eligible;
  end
  assign source_select[0] = i_chunk_end;
  assign source_select[1] = !i_chunk_end && (i_past_active || !i_active_after);
  assign source_select[2] = !i_chunk_end && !i_past_active && i_active_after && i_group_end;
  assign source_select[3] = !i_chunk_end && !i_past_active && i_active_after && !i_group_end;
  logic row_selected, tap_selected, column_selected;
  conv_stream_row_request u_row_request (
    .i_selected(source_select[0]), .i_last(i_row_last), .i_base_valid(i_row_base_valid),
    .i_geometry(i_geometry_tile), .i_padding(i_next_row_padding),
    .i_word_hit(i_next_row_word_hit), .o_request(row_selected)
  );
  conv_stream_tap_request u_tap_request (
    .i_selected(source_select[2]), .i_address_valid(i_coordinate_address_valid),
    .i_next_padding(i_next_tap_padding), .i_word_equal(i_next_word_equal),
    .i_padding(i_padding), .i_context(i_tap_context), .o_request(tap_selected)
  );
  conv_stream_column_request u_column_request (
    .i_selected(source_select[3]), .i_padding(i_padding), .i_boundary(i_word_boundary),
    .i_eligible(i_stream_eligible), .o_request(column_selected)
  );
  logic [2:0] request_selected;
  assign request_selected = {tap_selected, row_selected, tap_selected || column_selected};
  assign candidate[0] = {1'b0, row_request, 1'b0, row_state};
  assign candidate[1] = {3'b000, ZERO_STREAM};
  assign candidate[2] = {tap_request, 1'b0, tap_request, tap_state};
  assign candidate[3] = {2'b00, column_request, column_state};
  onehot_mux #(.p_choices(4), .p_width(30)) u_state_choice (
    .i_select(source_select), .i_data(candidate), .o_data(selected)
  );
  always_comb begin
`ifdef SYNTHESIS
    {o_tap_selected, o_row_selected, o_request_selected, o_state} = selected;
`else
    o_state = FETCH;
    o_request_selected = 1'b0;
    o_row_selected = 1'b0;
    o_tap_selected = 1'b0;
    if (i_chunk_end) begin
      o_state = row_state;
      o_row_selected = row_request;
    end else if (i_past_active || !i_active_after) begin
      o_state = ZERO_STREAM;
    end else if (i_group_end) begin
      o_state = tap_state;
      o_request_selected = tap_request;
      o_tap_selected = tap_request;
    end else begin
      o_state = column_state;
      o_request_selected = column_request;
    end
    case (^{i_chunk_end, i_past_active, i_active_after, i_group_end, candidate})
      1'b0, 1'b1: {o_tap_selected, o_row_selected, o_request_selected, o_state} = selected;
      default: ;
    endcase
`endif
    // 已知控制分别使用局部请求条件，未知控制保持原顺序选择结果。
    case (^{i_chunk_end, i_row_last, i_row_base_valid, i_geometry_tile,
        i_next_row_padding, i_next_row_word_hit, i_row_coordinate_valid,
        i_past_active, i_active_after, i_group_end, i_coordinate_address_valid,
        i_next_tap_padding, i_next_word_equal, i_padding, i_tap_context,
        i_word_boundary, i_stream_eligible})
      1'b0, 1'b1: {o_tap_selected, o_row_selected, o_request_selected} = request_selected;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
