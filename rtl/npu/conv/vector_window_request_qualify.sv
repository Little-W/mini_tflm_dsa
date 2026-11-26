// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 汇合已完成范围检查的空闲槽位资格和本拍释放资格，生成窗口请求有效信号。
(* keep_hierarchy = "yes" *)
module vector_window_request_qualify (
  input wire logic i_idle, // 当前槽位空闲且满足请求条件。
  input wire logic i_release_enabled, // 当前槽位允许在计算发射后立即接收请求。
  input wire logic i_release, // 当前计算发射并释放对应槽位。
  output logic o_valid // 空闲或同拍释放的槽位可以发送窗口请求。
);
  assign o_valid = i_idle || (i_release_enabled && i_release);
endmodule

`default_nettype wire
