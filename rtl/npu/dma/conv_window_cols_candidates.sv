// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 为前端保持和接收两种情况分别准备列数有效资格。
(* keep_hierarchy = "yes" *)
module conv_window_cols_candidates (
  input wire logic i_available, // 队列中存在可发送描述符
  input wire logic i_multiple, // 队列中有多个可发送描述符
  input wire logic i_accept, // 当前周期接收新请求
  input wire logic i_request, // 当前输入请求的列数有效资格
  input wire logic i_current, // 当前队首描述符的列数有效资格
  input wire logic i_next, // 下一个描述符的列数有效资格
  input wire logic i_saved, // 前一周期保存的列数有效资格
  output logic [1:0] o_value // 输出的列数有效资格
);
  assign o_value[0] = (i_multiple || i_available) ? i_current : (i_accept ? i_request : i_saved);
  assign o_value[1] = i_multiple ? i_next : (i_accept ? i_request : i_saved);
endmodule

`default_nettype wire
