// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按当前前端握手选择已准备的列数有效资格。
(* keep_hierarchy = "yes" *)
module conv_window_cols_select (
  input wire logic i_frontend_valid, // 送往前端的描述符有效
  input wire logic i_frontend_ready, // 前端允许接收描述符
  input wire logic [1:0] i_candidate, // 保持和接收两种情况下的列数有效资格
  output logic o_value // 输出的列数有效资格
);
  assign o_value = (i_frontend_valid && i_frontend_ready) ? i_candidate[1] : i_candidate[0];
endmodule

`default_nettype wire
