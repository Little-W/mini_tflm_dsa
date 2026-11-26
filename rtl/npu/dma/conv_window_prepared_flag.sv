// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 结合队列数量、描述符接收及前端握手，形成下一周期的准备标志。
(* keep_hierarchy = "yes" *)
module conv_window_prepared_flag (
  input wire logic i_configure, // 当前周期接收新的任务配置
  input wire logic i_multiple, // 队列中有多个可发送描述符
  input wire logic i_available, // 队列中存在可发送描述符
  input wire logic i_frontend_valid, // 送往前端的描述符有效
  input wire logic i_frontend_ready, // 前端允许接收描述符
  input wire logic i_accept, // 当前周期接收新请求
  output logic o_prepared // 下一周期存在已准备的描述符
);
  always_comb begin
    if (i_configure) o_prepared = 1'b0;
    else o_prepared = i_multiple || i_accept ||
        (i_available && !(i_frontend_valid && i_frontend_ready));
  end
endmodule

`default_nettype wire
