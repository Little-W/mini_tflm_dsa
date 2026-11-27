// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 描述符形状和接收资格提前归并，命中位直接进入最后的请求选择。
module conv_im2col_descriptor_request #(
  parameter int p_size = 16,
  parameter int p_rw = $clog2(p_size+1),
  parameter bit p_register_descriptor = 1'b0,
  parameter bit p_preview_registered = 1'b0
) (
  input wire logic i_tile_valid, // 输入分块描述符有效
  input wire logic i_tile_ready, // 当前周期允许接收分块
  input wire logic i_incoming_fast, // 输入描述符可复用已准备的上下文
  input wire logic [p_rw-1:0] i_tile_rows, // 输入分块的有效行数
  input wire logic [p_rw-1:0] i_tile_cols, // 输入分块的有效列数
  input wire logic i_tile_q_before_end, // 输入归约起点小于归约长度
  input wire logic i_tile_rows_in_range, // 输入分块的全部行处于空间范围内
  output logic o_eligible // 输入描述符具备快速读取资格
);
  assign o_eligible = (!p_register_descriptor || p_preview_registered) &&
      i_tile_valid && i_tile_ready && i_incoming_fast &&
      i_tile_rows != 0 && 32'(i_tile_rows) <= p_size && 32'(i_tile_cols) <= p_size &&
      i_tile_q_before_end && i_tile_rows_in_range;
endmodule

`default_nettype wire
