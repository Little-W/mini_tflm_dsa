// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行归并当前帧的计算、部分和与输出完成条件，命令活动状态参与末级选择。
(* keep_hierarchy = "yes" *)
module npu_frame_complete_select (
    input  logic i_frame_mode, // 当前任务使用部分和帧调度
    input  logic i_frame_active = 1'b1, // 当前帧命令已经接收且尚未完成
    input  logic i_frame_eligible, // 当前帧已启动且计算、输出条件均满足
    input  logic i_store_seen, // 已保存当前帧的部分和完成状态
    input  logic i_store_complete, // 当前周期收到部分和完成通知
    input  logic i_output_complete, // 普通任务的输出完成状态
    output logic o_complete // 当前执行任务满足完成条件
);
    (* keep = 1 *) logic frame_result_ready;
    assign frame_result_ready = i_frame_eligible && (i_store_seen || i_store_complete);
    assign o_complete = i_frame_mode ?
        (i_frame_active && frame_result_ready) : i_output_complete;
endmodule

`default_nettype wire
