// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 将当前任务错误、任务开始清零和高优先级错误归并为下一拍错误编码。
// 保留末级选择边界，使任务开始信号只经过本级组合选择即可进入错误寄存器。
(* keep_hierarchy = "yes" *)
module vector_engine_error_select (
  input wire logic [1:0] i_local, // 当前状态对应的错误保持或更新结果。
  input wire logic i_idle, // 当前控制器处于任务接收状态。
  input wire logic i_start, // 本周期接收新的向量计算任务。
  input wire logic i_override, // 存储、窗口或写回报告需要优先记录的错误。
  output logic [1:0] o_next // 下一时钟边沿保存的错误状态编码。
);
  always_comb begin
    o_next = i_local;
    if (i_idle && i_start) o_next = 2'b00;
    if (i_override) o_next = 2'b10;
  end
endmodule

`default_nettype wire
