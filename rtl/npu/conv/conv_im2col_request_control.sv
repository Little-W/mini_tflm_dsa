// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 描述符、当前读取和输出推进并行决定请求资格，末端统一归并。
module conv_im2col_request_control #(
  parameter int p_size = 16,
  parameter int p_rw = $clog2(p_size+1),
  parameter bit p_register_descriptor = 1'b0,
  parameter bit p_preview_registered = 1'b0
) (
  input wire logic i_tile_valid, // 输入分块描述符有效
  input wire logic i_tile_ready, // 当前周期允许接收分块
  input wire logic i_incoming_fast, // 输入描述符可复用已准备的上下文
  input wire logic i_incoming_padding, // 输入描述符的首个位置需要填充
  input wire logic i_incoming_word_hit, // 输入描述符命中可直接使用的数据字
  input wire logic [p_rw-1:0] i_tile_rows, // 输入分块的有效行数
  input wire logic [p_rw-1:0] i_tile_cols, // 输入分块的有效列数
  input wire logic i_tile_q_before_end, // 输入归约起点小于归约长度
  input wire logic i_tile_rows_in_range, // 输入分块的全部行处于空间范围内
  input wire logic i_fetch, // 运行状态要求读取当前数据字
  input wire logic i_current_word_hit, // 当前运行地址命中保存的数据字
  input wire logic i_wr_valid, // 输出数据有效
  input wire logic i_wr_ready, // 下游允许接收输出
  input wire logic i_stream_request_eligible, // 流式推进具备读取资格
  input wire logic i_row_request_eligible, // 下一行推进具备读取资格
  input wire logic i_tap_selected, // 选择下一卷积核读取请求
  output logic o_cache_req_valid // 当前缓存读取请求有效
);
  logic descriptor_request;
  logic fetch_request;
  logic output_request;
  logic descriptor_eligible;

  conv_im2col_descriptor_request #(
    .p_size(p_size), .p_rw(p_rw), .p_register_descriptor(p_register_descriptor),
    .p_preview_registered(p_preview_registered)
  ) u_descriptor_request (
    .i_tile_valid(i_tile_valid), .i_tile_ready(i_tile_ready), .i_incoming_fast(i_incoming_fast),
    .i_tile_rows(i_tile_rows), .i_tile_cols(i_tile_cols),
    .i_tile_q_before_end(i_tile_q_before_end), .i_tile_rows_in_range(i_tile_rows_in_range),
    .o_eligible(descriptor_eligible)
  );
  assign descriptor_request = descriptor_eligible && !i_incoming_padding && !i_incoming_word_hit;
  assign fetch_request = i_fetch && !i_current_word_hit;
  assign output_request = i_wr_valid && i_wr_ready &&
      (i_stream_request_eligible || i_row_request_eligible || i_tap_selected);
  assign o_cache_req_valid = descriptor_request || fetch_request || output_request;
endmodule

`default_nettype wire
