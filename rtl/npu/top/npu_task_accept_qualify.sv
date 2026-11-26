// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 汇总当前任务故障并形成新任务接收及向量启动资格，全部输出保持组合周期。
// 默认处理全部输入组合；专用模式用于向量运行状态与接收资格互斥的控制器。
(* keep_hierarchy = "yes" *)
module npu_task_accept_qualify #(
    parameter bit p_vector_capable = 1'b1, // 当前硬件配置具有向量执行能力
    parameter bit p_exclusive_vector = 1'b0 // 运行标志与保存的接收资格满足互斥不变量
) (
    input wire logic i_accept_ready, // 已保存的后台空闲及任务接收资格
    input wire logic i_abort_idle, // 当前中止控制器处于空闲状态
    input wire logic i_run_conv, // 当前运行任务使用卷积窗口读取
    input wire logic i_run_vector, // 当前运行任务使用向量引擎
    input wire logic i_conv_error, // 卷积窗口读取模块报告错误
    input wire logic [4:0] i_fault, // 容量、共享存储、总线及矩阵完成错误
    input wire logic i_calc_start, // 调用方提交新任务
    input wire logic i_vector_enable, // 待提交任务选择向量引擎
    input wire logic i_conv_enable, // 待提交任务选择矩阵卷积模式
    output logic o_ready, // 当前周期允许接收新任务
    output logic o_vector_start, // 当前周期正式提交向量任务
    output logic o_fault // 当前运行任务的完整故障状态
);
    logic other_fault;
    logic reference_ready;
    assign other_fault = |i_fault;
    assign o_fault = other_fault || ((i_run_conv || i_run_vector) && i_conv_error);
    assign reference_ready = i_accept_ready && i_abort_idle && !o_fault;

    // 接收边沿清除保存资格，向量任务结束前不会重新置位该资格。
    // 已知互斥状态直接检查其余故障；未知状态保持完整关系表达式的四态结果。
    always_comb begin
        o_ready = reference_ready;
        if (p_exclusive_vector) begin
            case (^{i_accept_ready, i_run_vector})
                1'b0, 1'b1: o_ready = i_accept_ready && i_abort_idle &&
                    !(other_fault || (i_run_conv && i_conv_error));
                default: ;
            endcase
        end
    end
    assign o_vector_start = p_vector_capable && i_calc_start && o_ready &&
        i_vector_enable && !i_conv_enable;
endmodule

`default_nettype wire
