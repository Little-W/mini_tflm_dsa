// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行准备的行、矩阵块行和存储体结束条件在末级归并，形成合并输出的组结束标志。
(* keep_hierarchy = "yes" *)
module vec_s8_fifo_group_end (
  input logic i_row_boundary, // 当前数据拍同时结束矩阵块列和当前输出行
  input logic i_transpose, // 当前合并输出采用转置布局
  input logic i_transpose_row_last, // 转置输出行号已到当前矩阵块的有效末行
  input logic i_tile_row_last, // 当前矩阵块行号已到合并分组的末行
  input logic i_bank_row_last, // 当前输出行已达到所选存储体的有效行数
  output logic o_group_last // 当前数据拍结束整个合并输出分组
);
  assign o_group_last = i_row_boundary &&
      (i_transpose ? i_transpose_row_last : (i_tile_row_last && i_bank_row_last));
endmodule

`default_nettype wire
