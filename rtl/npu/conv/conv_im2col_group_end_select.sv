// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 输出阶段和数据格式只选择已经完成的三个组末结果。
module conv_im2col_group_end_select (
  input wire logic i_word_output, // 当前输出使用缓存数据字
  input wire logic i_input_s16, // 输入样本采用十六位格式
  input wire logic [2:0] i_end, // 补零及两种数据格式对应的组末标志
  output logic o_end // 当前选择到达范围末尾
);
  assign o_end = i_word_output ? (i_input_s16 ? i_end[2] : i_end[1]) : i_end[0];
endmodule

`default_nettype wire
