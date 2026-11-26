// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在接收新请求、发送后预取或错误恢复时更新准备数据，等待期间保持当前字段。
(* keep_hierarchy = "yes" *)
module conv_window_data_enable (
  input wire logic i_available, // 队列中存在未发送描述符
  input wire logic i_multiple, // 队列中存在多个未发送描述符
  input wire logic i_accept, // 本周期接收新请求
  input wire logic i_launch, // 本周期发送当前已准备项
  input wire logic i_failed, // 队列处于错误恢复阶段
  output logic o_enable // 准备字段需要更新
);
  logic read_available;

  assign read_available = i_multiple || (!i_launch && i_available);
  assign o_enable = (read_available && (i_launch || i_failed)) ||
      (i_accept && !read_available);
endmodule

`default_nettype wire
