// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 直接归并六项输入条件，在当前步骤不需要读取偏置时形成完整发送候选。
// 帧位置和基址零值分别输入，允许各自与数据、控制准备过程并行完成。
(* keep_hierarchy = "yes" *)
module npu_bias_issue_optional (
    input wire logic i_eligible, // 数据、部分和、状态和输出空间允许发送
    input wire logic i_frame_mode, // 当前采用帧执行模式
    input wire logic i_base_nonzero, // 完整配置位宽内的偏置基址非零
    input wire logic i_frame_phase, // 当前数据流和帧位置要求读取偏置
    input wire logic i_visible_base_nonzero, // 直接执行时控制器可见的偏置基址非零
    input wire logic i_bias_available, // 已有偏置数据或当前计算无需重新读取偏置
    output logic o_qualified // 当前输入发送不需要等待通道地址检查
);
    assign o_qualified = i_eligible && (i_bias_available ||
        (i_frame_mode ? !(i_base_nonzero && i_frame_phase) : !i_visible_base_nonzero));
endmodule

`default_nettype wire
