// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在一个末级选择中合并三个偏置候选和当前任务的完成状态。
// 帧模式使用提前准备的帧内状态，直接执行模式使用输出完成信号。
(* keep_hierarchy = "yes" *)
module npu_bias_issue_select (
    input wire logic [2:0] i_candidates, // 可直接发送及两种数据流的零地址发送候选
    input wire logic i_frame_mode, // 当前任务采用帧执行模式
    input wire logic i_frame_incomplete, // 当前帧尚未完成计算、部分和或输出处理
    input wire logic i_output_complete, // 直接执行任务的输出已经结束
    output logic o_issue // 本周期触发输入数据发送
);
    assign o_issue = (|i_candidates) && (i_frame_mode ? i_frame_incomplete : !i_output_complete);
endmodule

`default_nettype wire
