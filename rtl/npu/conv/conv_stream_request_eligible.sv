// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同时归并列、归约、通道组和缓存字的推进结果，形成连续读取资格。
(* keep_hierarchy = "yes" *)
module conv_stream_request_eligible (
  input wire logic i_zero_stream, // 当前状态仅输出补零数据
  input wire logic i_column_after, // 本次输出之后仍有分块列
  input wire logic i_active_after, // 本次输出之后仍有有效归约数据
  input wire logic i_group_after, // 本次输出之后仍有同组通道
  input wire logic i_word_boundary, // 本次输出跨过当前缓存字边界
  output logic o_eligible // 当前输出完成后允许连续读取缓存字
);
  assign o_eligible = !i_zero_stream && i_column_after && i_active_after &&
      i_group_after && i_word_boundary;
endmodule

`default_nettype wire
