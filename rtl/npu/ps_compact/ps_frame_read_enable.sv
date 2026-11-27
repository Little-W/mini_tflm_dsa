// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并首行与后续行读取资格，帧接受脉冲只经过一次末级选择。
(* keep_hierarchy = "yes" *)
module ps_frame_read_enable (
    input wire logic i_request, // 当前帧请求仍然有效。
    input wire logic i_accept, // 当前周期接受帧命令。
    input wire logic i_accept_permit = 1'b1, // 当前执行模式允许接受命令使用部分和存储。
    input wire logic i_accepted, // 当前帧命令已经接受。
    input wire logic i_first_ready, // 首行状态及同地址访问检查允许读取。
    input wire logic i_continue_ready, // 后续行状态和解码缓冲空间允许读取。
    input wire logic i_fault, // 当前存储容量或访问状态存在错误。
    output logic o_read_enable // 当前周期向部分和存储发出读取请求。
);
    (* keep = 1 *) logic requested_read, accepted_read;
    // 请求状态和接受资格分别提前准备，接受脉冲仅参与最后的二路选择。
    assign requested_read = !i_fault &&
        ((i_request && i_first_ready) || ((i_request || i_accepted) && i_continue_ready));
    assign accepted_read = !i_fault && i_continue_ready && i_accept_permit;
    assign o_read_enable = requested_read || (i_accept && accepted_read);
endmodule

`default_nettype wire
