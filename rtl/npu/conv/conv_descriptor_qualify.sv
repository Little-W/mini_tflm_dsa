// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 合并描述符候选的资格条件，并按参数处理优先窗口的占用关系。
(* keep_hierarchy = "yes" *)
module conv_descriptor_qualify #(
  parameter int unsigned p_flags = 6,
  parameter logic [p_flags-1:0] p_expected = '1,
  parameter bit p_window_priority = 1'b0
) (
  input wire logic [p_flags-1:0] i_flags, // 当前候选的独立资格条件
  input wire logic [1:0] i_window, // 优先窗口的上下文及匹配条件
  output logic o_valid // 当前候选通过全部资格检查
);
  assign o_valid = (&(i_flags ~^ p_expected)) && (!p_window_priority || !(i_window[1] && i_window[0]));
endmodule

`default_nettype wire
