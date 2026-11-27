// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行形成描述符接收的四个前置条件，条件计算独立于当前列末和输入快速复用结果。
(* keep_hierarchy = "yes" *)
module conv_descriptor_admission_terms #(
  parameter bit p_register_descriptor = 1'b1
) (
  input wire logic i_idle, // 当前处于允许接收描述符的空闲阶段
  input wire logic i_output, // 当前输出已经满足行号、响应和写入接口条件
  input wire logic i_early, // 当前运行项允许提前准备下一描述符
  input wire logic i_prepared, // 准备槽中的描述符有效
  input wire logic [1:0] i_commit_context, // 空闲提交及输出末拍提交的独立前置条件
  input wire logic i_configure, // 当前周期提交新的卷积配置
  output logic [3:0] o_terms // 空闲普通、空闲快速、输出普通和输出快速四项许可
);
  logic ordinary;
  assign ordinary = !p_register_descriptor || !i_prepared;
  assign o_terms[0] = !i_configure && i_idle && ordinary;
  assign o_terms[1] = !i_configure && i_idle && i_commit_context[0];
  assign o_terms[2] = !i_configure && i_output && ordinary;
  assign o_terms[3] = !i_configure && ((i_idle && i_commit_context[1]) ||
      (i_output && (|i_commit_context)) || (i_early && (ordinary || (|i_commit_context))));
endmodule

`default_nettype wire
