// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 组内读取在有效位置跨越数据字边界时发出请求。
(* keep_hierarchy = "yes" *)
module conv_stream_column_request (
  input wire logic i_selected, // 当前选择组内连续推进。
  input wire logic i_padding, // 当前输入位置需要填充。
  input wire logic i_boundary, // 推进跨越数据字边界。
  input wire logic i_eligible, // 当前流式推进具备读取资格。
  output logic o_request // 组内下一位置需要请求缓存读取。
);
  assign o_request = i_selected && !i_padding && i_boundary && i_eligible;
endmodule

`default_nettype wire
