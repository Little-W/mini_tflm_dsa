// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 依据保存的请求资格与当前帧完成状态形成新帧准备使能。
// 帧控制和返回队列的完成条件并行准备，在本模块中直接选择当前命令槽。
(* keep_hierarchy = "yes" *)
module ps_frame_prepare_enable (
    input wire logic i_request_qualified, // 已保存的合法且容量足够的待处理请求
    input wire logic i_command_present, // 当前命令槽已保存一个帧命令
    input wire logic i_control_complete, // 当前帧控制状态已满足完成条件
    input wire logic i_data_idle, // 同步读取和解码返回队列均已空闲
    output logic o_eligible // 当前周期可以准备所保存的新帧
);
    assign o_eligible = i_request_qualified &&
        (!i_command_present || (i_control_complete && i_data_idle));
endmodule

`default_nettype wire
