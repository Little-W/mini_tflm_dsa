// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 地址资格独立译码，行位置不参与描述符候选数据的计算。
module conv_im2col_address_sources (
  input wire logic i_tap, // 选择下一卷积核位置。
  input wire logic i_incoming, // 选择正在接收的描述符。
  input wire logic i_row, // 选择下一输出行地址。
  input wire logic i_stream, // 选择连续读取地址。
  input wire logic i_row_metadata, // 保存请求时选择下一行元数据。
  output logic [4:0] o_cache, // 缓存地址的五个来源选择位。
  output logic [4:0] o_saved // 保存请求地址的五个来源选择位。
);
  assign o_cache[0] = !i_tap && i_incoming;
  assign o_cache[1] = i_tap;
  assign o_cache[2] = !i_tap && !i_incoming && i_row;
  assign o_cache[3] = !i_tap && !i_incoming && !i_row && i_stream;
  assign o_cache[4] = !i_tap && !i_incoming && !i_row && !i_stream;
  assign o_saved[0] = !i_row_metadata && !i_tap && i_incoming;
  assign o_saved[1] = !i_row_metadata && i_tap;
  assign o_saved[2] = i_row_metadata;
  assign o_saved[3] = !i_row_metadata && !i_tap && !i_incoming && i_stream;
  assign o_saved[4] = !i_row_metadata && !i_tap && !i_incoming && !i_stream;
endmodule
`default_nettype wire
