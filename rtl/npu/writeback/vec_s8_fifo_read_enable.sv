// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行形成普通输出和合并输出的读取请求，组结束状态在末级控制继续读取。
(* keep_hierarchy = "yes" *)
module vec_s8_fifo_read_enable (
  input logic i_coalesce, // 当前输出采用矩阵块行合并模式
  input logic i_group_start, // 开始读取新的合并分组
  input logic i_waiting_ready, // 等待中的合并输出存储体已准备好
  input logic i_group_fire, // 当前合并数据拍完成握手
  input logic i_group_last, // 当前数据拍结束整个合并分组
  input logic i_next_bank_ready, // 下一合并数据拍使用的存储体已准备好
  input logic i_stream_start, // 普通输出开始读取一个存储体
  input logic i_stream_next, // 普通输出继续读取下一数据拍
  input logic i_refresh_first, // 首拍等待期间重新读取新的输出方向
  output logic o_read_enable // 本拍对结果数据存储发出读取请求
);
  logic immediate_group_read;
  logic normal_read;

  assign immediate_group_read = i_group_start || i_waiting_ready;
  assign normal_read = i_stream_start || i_stream_next || i_refresh_first;
  assign o_read_enable = i_coalesce ?
      (immediate_group_read || (i_group_fire && !i_group_last && i_next_bank_ready)) : normal_read;
endmodule

`default_nettype wire
