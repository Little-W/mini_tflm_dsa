// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 汇总部分和、输入数据、计算尾部、参数和控制状态的输入发送资格。
// 偏置条件独立准备，部分和、输出容量和完成状态在最终组合层控制发送触发。
(* keep_hierarchy = "yes" *)
module npu_ia_issue_select (
    input wire logic i_ps_ready, // 部分和存储已准备接收当前帧
    input wire logic i_data_ready, // 输入数据有效且当前输入发送尚未结束
    input wire logic i_aux_ready, // 计算尾部与量化参数已经准备完成
    input wire logic i_state_ready, // 控制状态允许触发输入数据发送
    input wire logic i_output_complete = 1'b0, // 当前任务已完成，阻止发送新的计算组
    input wire logic i_output_full = 1'b0, // 输出缓冲容量不足，阻止当前计算组发送
    input wire logic i_bias_valid = 1'b1, // 当前计算组所需偏置数据有效
    input wire logic i_bias_optional = 1'b0, // 当前计算组无需等待偏置数据
    input wire logic i_bias_reused = 1'b0, // 当前计算组通过部分和回放继续计算，无需读取偏置
    output logic o_trigger, // 本周期触发输入数据发送
    output logic o_eligible // 数据、部分和、状态和输出空间已就绪，供末级检查偏置与任务完成
);
    logic operand_state_ready;
    (* keep = 1 *) logic bias_ready;
    // 数据、控制和偏置独立归并，最终五个条件由同一组合层选择。
    assign operand_state_ready = i_data_ready && i_aux_ready && i_state_ready;
    assign bias_ready = i_bias_valid || i_bias_optional || i_bias_reused;
    // 数据与计算准备独立归并，偏置和任务完成条件由外部末级选择使用。
    assign o_eligible = i_ps_ready && i_data_ready && i_aux_ready && i_state_ready && !i_output_full;
    assign o_trigger = i_ps_ready && operand_state_ready && !i_output_full &&
        bias_ready && !i_output_complete;
endmodule

`default_nettype wire
