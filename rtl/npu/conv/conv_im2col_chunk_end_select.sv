// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 字内覆盖和补零覆盖均提前完成，格式选择保留条件表达式的四态语义。
module conv_im2col_chunk_end_select (
  input wire logic i_first_column_allowed, // 本次输出的首通道位于有效列范围内
  input wire logic i_word_output, // 当前输出使用缓存数据字
  input wire logic i_input_s16, // 输入样本采用十六位格式
  input wire logic [2:0] i_format_end, // 两种样本格式及补零输出的末列标志
  output logic o_end // 当前选择到达范围末尾
);
  logic padding_end;
  assign padding_end = !i_word_output && i_format_end[2];
  assign o_end = !i_first_column_allowed ||
      (i_input_s16 ? (i_format_end[1] || padding_end) : (i_format_end[0] || padding_end));
endmodule

`default_nettype wire
