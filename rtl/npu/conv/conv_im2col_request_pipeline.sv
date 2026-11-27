// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同步保存完整缓存请求及预读字段，并利用已有请求和响应寄存级提前读取连续像素。
// 队列接收、取消、地址、索引和元数据采用同一写入条件，输出停顿时保持待发送项。
module conv_im2col_request_pipeline #(
  parameter int unsigned p_size = 16,
  parameter int unsigned p_count_width = $clog2(p_size+1),
  parameter int unsigned p_word_shift = 4,
  parameter int unsigned p_response_depth = 2,
  parameter bit p_registered = 1'b1,
  parameter bit p_lookahead = 1'b1
) (
  input wire logic i_clk, // 请求流水级时钟
  input wire logic i_rst_n, // 低有效异步复位
  input wire logic i_configure, // 当前周期接收新的卷积配置
  input wire logic i_error, // 当前任务已经记录错误
  input wire logic i_response_failure, // 当前返回发生错误并停止提前请求
  input wire logic i_tile_commit, // 当前周期提交新的运行分块
  input wire conv_im2col_pkg::conv_cfg_t i_configuration, // 当前任务的输入格式和空间尺寸
  input wire logic i_request_valid, // 运行或描述符需要发出缓存请求
  input wire logic i_cache_ready, // 缓存允许接收请求寄存器中的项目
  input wire logic i_cancel, // 当前保存请求可以复用已有数据字
  input wire logic [31:0] i_address, // 普通请求的完整字节地址
  input wire logic [31:0] i_pixel, // 普通请求的完整像素位置
  input wire logic [31:0] i_index_reference, // 普通请求经过窗口缩放后的完整索引
  input wire logic i_short_pixel, // 请求索引按窗口粒度缩放
  input wire logic [4:0] i_index_shift, // 请求索引的窗口右移位数
  input wire logic i_index_valid, // 请求包含有效的窗口索引
  input wire logic i_geometry, // 请求使用几何预测格式
  input wire logic i_event_first, // 请求位于几何预测事件的首拍
  input wire logic [31:0] i_epoch, // 请求所属的通道纪元
  input wire logic [15:0] i_y, // 请求对应的输入行坐标
  input wire logic [31:0] i_progress, // 请求对应的输出行进度
  input wire logic i_stream, // 当前运行项正在等待或输出缓存数据
  input wire logic i_row_eligible, // 下一分块行已经具备读取资格
  input wire logic i_row_wrap, // 下一分块行跨越输出图像行边界
  input wire logic i_narrow, // 当前分块限制输出通道数量
  input wire logic i_past_active, // 当前输出已经越过有效归约范围
  input wire logic [p_count_width-1:0] i_row, // 当前运行项的分块行号
  input wire logic [p_count_width-1:0] i_rows, // 当前分块包含的行数
  input wire logic [p_count_width-1:0] i_column, // 当前输出的分块列号
  input wire logic [p_count_width-1:0] i_columns, // 当前分块每行的总列数
  input wire logic [p_count_width-1:0] i_active_columns, // 当前分块每行的有效列数
  input wire logic [15:0] i_channel, // 当前运行通道号
  input wire logic [15:0] i_initial_channel, // 分块每行起点的通道号
  input wire logic [p_count_width-1:0] i_next_row, // 下一分块行号
  input wire logic [15:0] i_next_input_x, // 下一分块行的输入列坐标
  input wire logic [15:0] i_output_x, // 当前输出列坐标
  input wire logic [31:0] i_seed_address, // 已准备的下一分块行字节地址
  input wire logic [31:0] i_seed_pixel, // 已准备的下一分块行完整像素位置
  output logic o_request_valid, // 本周期需要进入请求流水级的项目有效
  output logic o_request_ready, // 运行状态可继续其缓存请求步骤
  output logic o_capture_ready, // 本周期允许同时保存请求数据和元数据
  output logic o_cache_valid, // 缓存端口的正式请求有效
  output logic o_pending, // 请求寄存器中保存了有效项目
  output logic o_preview_valid, // 已保存地址与索引可以用于同步预读
  output logic [31:0] o_address, // 已保存请求的完整字节地址
  output logic [31:0] o_index, // 已保存请求的完整窗口索引
  output logic o_index_valid, // 已保存请求的窗口索引有效
  output logic o_geometry, // 已保存请求使用几何预测格式
  output logic o_event_first, // 已保存请求位于几何事件首拍
  output logic [31:0] o_epoch, // 已保存请求的通道纪元
  output logic [15:0] o_y, // 已保存请求的输入行坐标
  output logic [31:0] o_progress // 已保存请求的输出行进度
);
  logic capture_ready, lookahead_active, lookahead_issue, lookahead_preissued, lookahead_continuing;
  logic [31:0] saved_pixel, selected_address;
  logic [31:0] selected_pixel, selected_reference;
  logic [2:0] request_select;
  logic preview_next;

  assign capture_ready = !o_pending || i_cache_ready || i_cancel;
  conv_im2col_row_lookahead #(
    .p_size(p_size), .p_count_width(p_count_width), .p_word_shift(p_word_shift),
    .p_enabled(p_lookahead && p_registered && p_response_depth > 1)
  ) u_lookahead (
    .i_clk, .i_rst_n, .i_clear(i_configure || i_error || i_response_failure || i_tile_commit),
    .i_configuration, .i_stream, .i_row_eligible, .i_row_wrap, .i_narrow, .i_past_active,
    .i_row, .i_rows, .i_column, .i_columns, .i_active_columns, .i_channel, .i_initial_channel,
    .i_next_row, .i_next_input_x, .i_output_x, .i_capture_ready(capture_ready),
    .o_active(lookahead_active), .o_issue(lookahead_issue), .o_preissued(lookahead_preissued),
    .o_continuing(lookahead_continuing)
  );
  assign o_request_valid = !i_error &&
      (lookahead_issue || (i_request_valid && !lookahead_preissued));
  assign o_request_ready = p_registered ? capture_ready || lookahead_preissued : i_cache_ready;
  assign o_capture_ready = capture_ready && (!lookahead_active || o_request_valid);
  assign o_cache_valid = p_registered ? o_pending && !i_cancel : o_request_valid;
  always_comb begin
    request_select = 3'b001;
    if (lookahead_issue)
      request_select = lookahead_continuing ? 3'b100 : 3'b010;
  end
  conv_im2col_request_payload #(.p_word_shift(p_word_shift)) u_payload (
    .i_select(request_select), .i_address, .i_pixel, .i_seed_address, .i_seed_pixel,
    .i_saved_address(o_address), .i_saved_pixel(saved_pixel),
    .o_address(selected_address), .o_pixel(selected_pixel)
  );
  assign selected_reference = lookahead_issue ?
      (i_short_pixel ? selected_pixel >> i_index_shift : selected_pixel) : i_index_reference;
  always_comb begin
    preview_next = p_registered && o_request_valid && o_capture_ready;
    case (o_capture_ready)
      1'b1: preview_next = p_registered;
      default: begin end
    endcase
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_pending <= 1'b0;
      o_preview_valid <= 1'b0;
    end else begin
      o_preview_valid <= preview_next;
      if (p_registered ? capture_ready : i_cache_ready)
        o_pending <= p_registered && o_request_valid;
    end
  end
  always_ff @(posedge i_clk) begin
    if (o_capture_ready) begin
      o_address <= selected_address;
      o_index_valid <= i_index_valid;
      if (!(lookahead_active && lookahead_issue)) begin
        o_geometry <= i_geometry;
        o_event_first <= i_event_first;
        o_epoch <= i_epoch;
        o_y <= i_y;
        o_progress <= i_progress;
      end
    end
  end
  conv_request_index_register u_request_index_register (
    .i_clk, .i_write(o_capture_ready), .i_pixel(selected_pixel),
    .i_short_pixel, .i_shift(i_index_shift), .i_reference(selected_reference),
    .o_index, .o_pixel(saved_pixel)
  );
endmodule

`default_nettype wire
