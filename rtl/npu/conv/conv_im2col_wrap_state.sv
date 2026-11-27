// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 为配置、描述符和运行操作准备回绕候选，并保存三个位置对应的回绕标志。
(* keep_hierarchy = "yes" *)
module conv_im2col_wrap_state (
  input wire logic clk, // 回绕状态寄存器的工作时钟。
  input wire logic rst_n, // 低有效异步复位。
  input wire logic i_cfg_valid, // 新卷积配置有效。
  input wire logic i_cfg_ready, // 新卷积配置可被接收。
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前运行状态。
  input wire logic i_tile_commit, // 当前周期接收分块描述符。
  input wire logic i_descriptor_invalid, // 待接收描述符参数无效。
  input wire logic i_descriptor_fast, // 待接收描述符具有快速路径数据。
  input wire logic i_position_update, // 待接收描述符需要更新输出位置。
  input wire logic i_stream_error, // 当前运行请求返回错误。
  input wire logic i_stream_accept, // 当前运行输出被接收。
  input wire logic i_chunk_end, // 当前传输到达输出行末。
  input wire logic i_row_last, // 当前输出行为分块最后一行。
  input wire logic i_past_active, // 当前列已经越过有效输出范围。
  input wire logic i_active_after, // 当前传输之后仍有有效输出列。
  input wire logic i_group_end, // 当前传输到达通道组末尾。
  input wire logic i_row_wrap, // 输出位置沿列推进时换行。
  input wire logic i_tap_wrap, // 卷积核位置沿列推进时换行。
  input wire logic i_fast_position_valid, // 输出位置快速解码结果有效。
  input wire logic [31:0] i_decode_index, // 通用除法解码的当前计数。
  input wire logic [31:0] i_position, // 分块起始输出位置。
  input wire logic [31:0] i_tap, // 分块初始卷积核位置。
  input wire logic i_kernel_shape_valid, // 卷积核宽度支持位移解码。
  input wire logic [15:0] i_kernel_width, // 卷积核列数。
  input wire logic [5:0] i_row_candidate, // 配置、描述符和解码得到的输出行回绕候选。
  input wire logic [8:0] i_tap_candidate, // 配置、描述符和解码得到的卷积核回绕候选。
  output logic [2:0] o_wrap // 输出行、当前核位置和初始核位置的回绕标志。
);
  import conv_im2col_frontend_pkg::*;
  logic [3:0][5:0] wrap_update_candidate;
  logic [2:0] wrap_write;
  logic [2:0] wrap_value;
  logic wrap_cfg_fire;
  logic wrap_descriptor_check;
  logic wrap_running_state;

  logic decode_position_equal, decode_tap_equal;
  // 位置和核索引的完整匹配并行归并，回绕选择只读取一位结果。
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_decode_position_match (
    .i_a(i_decode_index), .i_b(i_position), .o_equal(decode_position_equal)
  );
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_decode_tap_match (
    .i_a(i_decode_index), .i_b(i_tap), .o_equal(decode_tap_equal)
  );
  // 各运行来源先准备回绕值与写入资格，接收事件只选择完整结果。
  assign wrap_cfg_fire = i_cfg_valid && i_cfg_ready;
  assign wrap_descriptor_check = i_state[$clog2(DESCRIPTOR_CHECK)];
  assign wrap_running_state = i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)];
  always_comb begin
    wrap_update_candidate[0] = {3'b111, i_tap_candidate[1], i_tap_candidate[0], i_row_candidate[0]};
    wrap_update_candidate[1] = '0;
    if (i_descriptor_invalid) begin
    end else if (i_descriptor_fast) begin
      wrap_update_candidate[1][5:4] = 2'b11;
      wrap_update_candidate[1][2:1] = {2{i_tap_candidate[2]}};
      if (i_position_update) begin
        wrap_update_candidate[1][3] = 1'b1;
        wrap_update_candidate[1][0] = i_row_candidate[1];
      end
    end
    wrap_update_candidate[2] = '0;
    if (i_chunk_end) begin
      if (i_row_last) begin
      end else begin
        wrap_update_candidate[2][4:3] = 2'b11;
        wrap_update_candidate[2][1] = i_tap_candidate[3];
        if (i_row_wrap) wrap_update_candidate[2][0] = i_row_candidate[2];
        else wrap_update_candidate[2][0] = i_row_candidate[3];
      end
    end else if (i_past_active || !i_active_after) begin
    end else if (i_group_end) begin
      wrap_update_candidate[2][4] = 1'b1;
      if (i_tap_wrap) wrap_update_candidate[2][1] = i_tap_candidate[4];
      else wrap_update_candidate[2][1] = i_tap_candidate[5];
    end
    wrap_update_candidate[3] = '0;
    case (1'b1)
      i_state[$clog2(P_HISTORY)]: ;
      i_state[$clog2(P_DECODE)]: if (i_fast_position_valid) begin
        wrap_update_candidate[3][3] = 1'b1;
        wrap_update_candidate[3][0] = i_row_candidate[4];
      end
      i_state[$clog2(P_START)]: ;
      i_state[$clog2(P_WAIT)]: if (decode_position_equal) begin
        wrap_update_candidate[3][3] = 1'b1;
        wrap_update_candidate[3][0] = i_row_candidate[5];
      end
      i_state[$clog2(Q_DECODE)]: ;
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: ;
      i_state[$clog2(K_DECODE)]: begin
        if (i_kernel_shape_valid) begin
          wrap_update_candidate[3][5:4] = 2'b11;
          wrap_update_candidate[3][2:1] = {2{i_tap_candidate[6]}};
        end else if (i_kernel_width == 16'd3 && i_tap < 32'd9) begin
          wrap_update_candidate[3][5:4] = 2'b11;
          wrap_update_candidate[3][2:1] = {2{i_tap_candidate[7]}};
        end
      end
      i_state[$clog2(K_START)]: ;
      i_state[$clog2(K_WAIT)]: if (decode_tap_equal) begin
        wrap_update_candidate[3][5:4] = 2'b11;
        wrap_update_candidate[3][2:1] = {2{i_tap_candidate[8]}};
      end
      default: ;
    endcase
  end
  conv_im2col_wrap_update_select u_wrap_update (
    .i_configuration(wrap_cfg_fire), .i_commit(i_tile_commit),
    .i_descriptor_check(wrap_descriptor_check), .i_stream_error(i_stream_error),
    .i_stream_accept(i_stream_accept), .i_running(wrap_running_state),
    .i_candidate(wrap_update_candidate), .o_write(wrap_write), .o_value(wrap_value)
  );

  // 输出行和卷积核回绕标志保持原有写入边沿与配置优先级。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      o_wrap[0] <= 1'b0;
      o_wrap[1] <= 1'b0;
      o_wrap[2] <= 1'b0;
    end else begin
      if (wrap_write[0]) o_wrap[0] <= wrap_value[0];
      if (wrap_write[1]) o_wrap[1] <= wrap_value[1];
      if (wrap_write[2]) o_wrap[2] <= wrap_value[2];
    end
  end

endmodule
`default_nettype wire
