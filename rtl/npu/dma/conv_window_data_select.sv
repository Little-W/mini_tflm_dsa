// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据未发送项数量和本周期发送事件，选择预取字段或新接收请求字段。
// 读取地址已提前确定，本模块仅形成准备寄存器的末级数据选择。
(* keep_hierarchy = "yes" *)
module conv_window_data_select #(
  parameter int unsigned p_width = 32
) (
  input wire logic i_available, // 队列中存在未发送描述符
  input wire logic i_multiple, // 队列中存在多个未发送描述符
  input wire logic i_launch, // 本周期发送当前已准备项
  input wire logic [p_width-1:0] i_read, // 预先读取的描述符字段
  input wire logic [p_width-1:0] i_request, // 新接收请求的描述符字段
  output logic [p_width-1:0] o_value // 本周期可保存的准备字段
);
  assign o_value = (i_multiple || (!i_launch && i_available)) ? i_read : i_request;
endmodule

`default_nettype wire
