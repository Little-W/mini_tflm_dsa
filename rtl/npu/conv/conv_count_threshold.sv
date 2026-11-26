// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 独立比较固定通道编号和剩余数量，输出完整定宽比较结果。
(* keep_hierarchy = "yes" *)
module conv_count_threshold #(
  parameter int p_width = 5,
  parameter int p_threshold = 0
) (
  input wire logic [p_width-1:0] i_count, // 当前保存或准备的剩余数量
  output logic o_above // 剩余数量大于固定通道编号
);
  assign o_above = p_width'(p_threshold) < i_count;
endmodule

`default_nettype wire
