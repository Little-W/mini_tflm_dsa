// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并已保存帧、空闲槽和当前帧完成后的接收资格，直接产生请求就绪信号。
(* keep_hierarchy = "yes" *)
module ps_frame_ready_select (
    input wire logic i_request, // 当前周期存在待接收的帧请求。
    input wire logic i_fault, // 部分和存储处于容量故障状态。
    input wire logic i_existing, // 已保存且尚未接受的命令已经完成读取准备。
    input wire logic i_idle, // 空闲命令槽已满足新帧准备条件。
    input wire logic i_completing, // 当前命令完成后可以立即接收新帧。
    input wire logic i_data_idle, // 返回流水线与解码队列均已清空。
    output logic o_ready // 当前帧请求可以在本周期被接收。
);
    assign o_ready = i_request && !i_fault &&
        (i_existing || i_idle || (i_completing && i_data_idle));
endmodule

`default_nettype wire
