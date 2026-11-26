// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分别准备五种运行地址的写入资格，组末和列末条件直接选择对应来源。
(* keep_hierarchy = "yes" *)
module conv_stream_address_select (
  input wire logic i_commit, // 当前周期提交已经准备的描述符
  input wire logic i_invalid, // 提交描述符的范围无效
  input wire logic i_fast, // 提交描述符具备直接地址上下文
  input wire logic i_transfer, // 当前输出传输已经接受
  input wire logic i_chunk_end, // 当前传输到达分块行末
  input wire logic i_row_last, // 当前行是分块的最后一行
  input wire logic i_row_valid, // 下一行的地址上下文有效
  input wire logic i_geometry, // 当前分块使用几何访问方式
  input wire logic i_column_advance, // 当前传输继续推进有效归约列
  input wire logic i_group_end, // 当前传输到达通道组末尾
  input wire logic i_coordinate_valid, // 下一卷积核的地址上下文有效
  input wire logic i_address_channel, // 当前状态提交通道计算地址
  output logic [4:0] o_select // 描述符、行、卷积核、连续字节和通道地址的选择资格
);
  assign o_select[0] = i_commit && !i_invalid && i_fast;
  assign o_select[1] = i_transfer && i_chunk_end && !i_row_last && i_row_valid && !i_geometry;
  assign o_select[2] = i_transfer && i_column_advance && i_group_end && i_coordinate_valid;
  assign o_select[3] = i_transfer && i_column_advance && !i_group_end;
  assign o_select[4] = i_address_channel;
endmodule

`default_nettype wire
