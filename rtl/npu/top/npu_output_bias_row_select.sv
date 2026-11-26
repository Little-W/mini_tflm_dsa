// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在行索引更新末端选择组首清零，较晚到达的启动资格仅通过最终选择级。
(* keep_hierarchy = "yes" *)
module npu_output_bias_row_select #(
    parameter int unsigned p_width = 9
) (
    input wire logic [p_width-1:0] i_step, // 已完成保持、递增和行尾回绕选择的索引。
    input wire logic i_init, // 当前周期初始化偏置分组。
    input wire logic i_mode, // 当前任务使用输入驻留计算模式。
    input wire logic i_start, // 当前周期触发下一输入组。
    input wire logic i_sleep, // 偏置组处于暂停状态。
    output logic [p_width-1:0] o_next // 下一周期使用的偏置行索引。
);
    assign o_next = (i_init || (i_mode && i_start && !i_sleep)) ? '0 : i_step;
endmodule

`default_nettype wire
