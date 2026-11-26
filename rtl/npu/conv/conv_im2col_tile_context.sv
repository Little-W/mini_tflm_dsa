// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 空闲与输出完成分别准备接收资格，缓存返回在外层完成末级选择。
(* keep_hierarchy = "yes" *)
module conv_im2col_tile_context (
  input wire logic i_static_ready, // 配置和准备阶段允许接收描述符。
  input wire logic i_idle, // 当前运行状态空闲。
  input wire logic i_stream, // 当前状态输出已保存的缓存字。
  input wire logic i_zero_stream, // 当前状态输出填充值。
  input wire logic i_wait_word, // 当前状态等待缓存响应。
  input wire logic i_write_ready, // 写入接口能够接收当前输出。
  input wire logic i_row_last, // 当前输出行为描述符最后一行。
  input wire logic i_chunk_end, // 当前传输到达输出行末。
  output logic [1:0] o_ready // 常规输出和缓存响应场景的描述符接收资格。
);
  logic transfer_last;
  assign transfer_last = i_write_ready && i_row_last && i_chunk_end;
  assign o_ready[0] = i_static_ready && (i_idle || ((i_stream || i_zero_stream) && transfer_last));
  assign o_ready[1] = i_static_ready && i_wait_word && transfer_last;
endmodule
`default_nettype wire
