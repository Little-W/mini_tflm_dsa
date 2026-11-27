// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存准备描述符的首字读取归属、数据字标签和单拍范围。
// 提前请求同时保存前一准备项的标签，下一周期只比较寄存标签并取消重复读取。
module conv_descriptor_read_state #(
  parameter int p_word_shift = 3,
  parameter int p_lanes = 8,
  parameter int p_narrow_lanes = 4,
  parameter bit p_enabled = 1'b1
) (
  input wire logic i_clk, // 状态寄存器时钟
  input wire logic i_rst_n, // 低有效异步复位
  input wire logic i_configure, // 接收新卷积配置并清除读取状态
  input wire logic i_error, // 当前任务错误并清除读取状态
  input wire logic i_accept, // 接收新的准备描述符
  input wire logic i_commit, // 准备描述符转入运行项
  input wire logic i_read_fire, // 新描述符的首字候选进入请求寄存器
  input wire logic i_response_consumed, // 当前运行项已经消费缓存响应
  input wire logic i_prepared_valid, // 当前存在尚未提交的准备描述符
  input wire logic i_request_write, // 请求寄存器本周期保存新候选
  input wire logic i_request_pending, // 请求寄存器内存在有效候选
  input wire logic [31:p_word_shift] i_request_tag, // 已寄存请求地址的数据字标签
  input wire logic [31:0] i_incoming_address, // 待接收描述符的完整首地址
  input wire logic [31:0] i_columns, // 待接收描述符的有效列数
  input wire logic i_one_row, // 待接收描述符只有一行
  input wire logic i_narrow, // 待接收描述符限制输出通道数量
  input wire logic i_input_s16, // 输入样本占两个字节
  input wire logic i_fast, // 待接收描述符的快速上下文有效
  input wire logic i_padding, // 待接收描述符的首位置需要填充
  input wire logic i_group_fits, // 待接收描述符的列数处于当前通道组内
  input wire logic i_word_hit, // 待接收描述符命中运行数据字或当前响应
  output logic o_prepared_pending, // 准备项首字已经提交读取候选
  output logic o_active_pending, // 运行项正在等待其首字响应
  output logic [31:p_word_shift] o_prepared_tag, // 准备项实际首地址的数据字标签
  output logic o_prepared_word_ready, // 准备项可以复用已存在的数据字
  output logic o_single_word, // 准备项可在一个输出拍和一个数据字内完成
  output logic o_request_cancel // 当前请求复用前一准备项的数据字
);
  localparam int p_word_bytes = 1 << p_word_shift;
  logic prepared_shape_q;
  logic [p_word_shift-1:0] prepared_offset_q;
  logic [31:0] prepared_bytes_q;
  logic compare_valid_q, tag_equal;
  logic [31:p_word_shift] previous_tag_q;

  // 首地址低位和传输字节数在接收边沿保存，范围加法位于寄存器之后。
  assign o_single_word = prepared_shape_q &&
      (32'(prepared_offset_q) + prepared_bytes_q <= 32'(p_word_bytes));
  always_ff @(posedge i_clk) begin
    if (i_accept) begin
      o_prepared_tag <= i_incoming_address[31:p_word_shift];
      prepared_offset_q <= i_incoming_address[p_word_shift-1:0];
      prepared_bytes_q <= i_columns << i_input_s16;
      prepared_shape_q <= i_fast && !i_padding && i_one_row &&
          i_columns <= 32'(p_lanes) && (!i_narrow || i_columns <= 32'(p_narrow_lanes)) && i_group_fits;
      o_prepared_word_ready <= i_word_hit;
    end else if (o_request_cancel) o_prepared_word_ready <= 1'b1;
    if (i_request_write) previous_tag_q <= o_prepared_tag;
  end
  conv_descriptor_match #(.p_width(32-p_word_shift), .p_preserve_groups(1'b1), .p_reduce_group_width(6)) u_request_match (
    .i_a(i_request_tag), .i_b(previous_tag_q), .o_equal(tag_equal)
  );
  assign o_request_cancel = p_enabled && compare_valid_q && i_request_pending && tag_equal;

  // 接收新项时写入其标志，提交时读取旧准备项标志；重复请求不进入缓存队列。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_prepared_pending <= 1'b0;
      o_active_pending <= 1'b0;
      compare_valid_q <= 1'b0;
    end else if (i_configure || i_error) begin
      o_prepared_pending <= 1'b0;
      o_active_pending <= 1'b0;
      compare_valid_q <= 1'b0;
    end else begin
      if (i_request_write) compare_valid_q <= p_enabled && i_read_fire && i_prepared_valid &&
          o_single_word && (o_prepared_pending || o_prepared_word_ready);
      if (i_accept) o_prepared_pending <= i_read_fire;
      else if (i_commit || o_request_cancel) o_prepared_pending <= 1'b0;
      if (i_commit) o_active_pending <= o_prepared_pending && !o_request_cancel;
      else if (i_response_consumed) o_active_pending <= 1'b0;
    end
  end
endmodule

`default_nettype wire
