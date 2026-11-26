// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 传输接收选择两个已经完成的运行结果。
module conv_im2col_error_operation_select (
  input wire logic i_accept, // 当前输出传输被接收。
  input wire logic [1:0] i_waiting, // 等待传输时的完整错误标志。
  input wire logic [1:0] i_accepted, // 传输被接收时的完整错误标志。
  output logic [1:0] o_value // 当前周期需要保存的完整错误标志。
);
  assign o_value = i_accept ? i_accepted : i_waiting;
endmodule
`default_nettype wire
