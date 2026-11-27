// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在同一分块和输出行内提前请求连续完整像素，使用现有请求寄存器保存地址游标。
// 返回仍由缓存队列按接收次序保存；本模块记录已发出的行号及空间边界。
module conv_im2col_row_lookahead #(
  parameter int unsigned p_size = 16,
  parameter int unsigned p_count_width = $clog2(p_size+1),
  parameter int unsigned p_word_shift = 4,
  parameter bit p_enabled = 1'b1
) (
  input wire logic i_clk, // 提前请求状态的时钟
  input wire logic i_rst_n, // 低有效异步复位
  input wire logic i_clear, // 配置接收、分块提交或错误清空提前请求状态
  input wire conv_im2col_pkg::conv_cfg_t i_configuration, // 当前输入格式、空间尺寸和步长
  input wire logic i_stream, // 当前运行项正在等待或输出缓存数据
  input wire logic i_row_eligible, // 当前运行项的下一行可以发起缓存读取
  input wire logic i_row_wrap, // 当前输出位置的下一行跨越输出图像行边界
  input wire logic i_narrow, // 当前分块使用窄输出格式
  input wire logic i_past_active, // 当前输出已越过有效归约范围
  input wire logic [p_count_width-1:0] i_row, // 当前正在输出的分块行号
  input wire logic [p_count_width-1:0] i_rows, // 当前分块包含的行数
  input wire logic [p_count_width-1:0] i_column, // 当前输出在分块行中的列号
  input wire logic [p_count_width-1:0] i_columns, // 当前分块每行的总列数
  input wire logic [p_count_width-1:0] i_active_columns, // 当前分块每行的有效列数
  input wire logic [15:0] i_channel, // 当前卷积核位置中的通道号
  input wire logic [15:0] i_initial_channel, // 当前分块各行起点的通道号
  input wire logic [p_count_width-1:0] i_next_row, // 当前运行项的下一分块行号
  input wire logic [15:0] i_next_input_x, // 下一分块行对应的有效输入列坐标
  input wire logic [15:0] i_output_x, // 当前输出列坐标
  input wire logic i_capture_ready, // 现有请求寄存器允许接收新的请求
  output logic o_active, // 当前分块已建立连续像素提前请求上下文
  output logic o_issue, // 当前候选需要进入请求寄存器
  output logic o_preissued, // 当前运行项的下一行已经发出请求
  output logic o_continuing // 当前候选使用已经建立的连续像素上下文
);
  localparam int unsigned p_word_bytes = 1 << p_word_shift;
  logic active_q, format_ready, seed_ready, continuing_ready;
  logic [p_count_width-1:0] issued_row_q, following_row;
  logic [16:0] following_input_x, following_output_x;
  logic [15:0] input_step_source, output_step_source, seed_output_x;
  logic [16:0] next_input_x, next_output_x;
  logic capture, drained;

  assign format_ready = p_enabled && p_word_bytes <= p_size &&
      !i_configuration.input_s16 && i_configuration.input_c == 16'(p_word_bytes) &&
      i_configuration.group_c == 16'(p_word_bytes) && i_configuration.group_offset == 0 &&
      i_configuration.stride_w == 16'd1 && i_configuration.input_base[p_word_shift-1:0] == 0 &&
      i_column == 0 && i_columns == p_count_width'(p_word_bytes) &&
      i_active_columns == p_count_width'(p_word_bytes) &&
      i_channel == 0 && i_initial_channel == 0 && !i_narrow && !i_past_active;
  assign seed_ready = format_ready && i_stream && i_row_eligible && !i_row_wrap &&
      i_next_row < i_rows;
  assign following_row = issued_row_q + p_count_width'(1);
  assign seed_output_x = i_output_x + 16'd1;
  always_comb begin
    input_step_source = i_next_input_x;
    output_step_source = seed_output_x;
    if (active_q) begin
      input_step_source = following_input_x[15:0];
      output_step_source = following_output_x[15:0];
    end
  end
  conditional_increment #(.p_width(17), .p_group_width(6)) u_input_step (
    .i_value({1'b0,input_step_source}), .i_enable(1'b1), .o_result(next_input_x)
  );
  conditional_increment #(.p_width(17), .p_group_width(6)) u_output_step (
    .i_value({1'b0,output_step_source}), .i_enable(1'b1), .o_result(next_output_x)
  );
  assign continuing_ready = format_ready && i_stream &&
      following_row < i_rows &&
      following_input_x < {1'b0,i_configuration.input_w} &&
      following_output_x < {1'b0,i_configuration.output_w};
  assign drained = active_q && !continuing_ready && i_row >= issued_row_q;

  always_comb begin
    o_active = p_enabled && active_q && !drained;
    o_issue = 1'b0;
    o_preissued = 1'b0;
    o_continuing = 1'b0;
    if (active_q) begin
      o_continuing = 1'b1;
      case (format_ready && i_stream && !i_clear && i_next_row <= issued_row_q)
        1'b1: o_preissued = 1'b1;
        default: begin end
      endcase
      case (continuing_ready && !i_clear)
        1'b1: o_issue = 1'b1;
        default: begin end
      endcase
    end else begin
      case (seed_ready && !i_clear)
        1'b1: o_issue = 1'b1;
        default: begin end
      endcase
    end
  end
  assign capture = o_issue && i_capture_ready;
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) active_q <= 1'b0;
    else if (i_clear || drained) active_q <= 1'b0;
    else if (capture) active_q <= 1'b1;
  end
  always_ff @(posedge i_clk) begin
    if (capture) begin
      following_input_x <= next_input_x;
      following_output_x <= next_output_x;
      if (active_q) begin
        issued_row_q <= following_row;
      end else begin
        issued_row_q <= i_next_row;
      end
    end
  end
endmodule

`default_nettype wire
