// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并通道组的高低位边界条件，生成当前通道的有效资格。
module conv_channel_range_compare #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1,
    parameter int unsigned p_lane = 0
) (
    input  wire logic [p_width-1:0] i_remaining_low, // 剩余有效通道数量的低位部分
    input  wire logic [p_width-1:0] i_channel_low, // 当前通道坐标的低位部分
    input  wire logic i_remaining_borrow, // 剩余通道差值的借位标志
    input  wire logic i_high_nonzero, // 剩余有效通道数量的高位非零标志
    input  wire logic i_channel_high_last, // 当前通道所在高位组为最后一组
    output logic o_allowed // 当前通道位于允许访问的范围内
);
    logic outside_interval;
    logic channel_wrap_threshold;
    conv_channel_outside_interval #(.p_width(p_width), .p_step(p_step), .p_lane(p_lane)) u_interval (
        .i_remaining_low(i_remaining_low), .o_outside(outside_interval)
    );
    conv_channel_wrap_threshold #(.p_width(p_width), .p_step(p_step)) u_wrap (
        .i_channel_low(i_channel_low), .o_wrap(channel_wrap_threshold)
    );
    assign o_allowed = i_high_nonzero ||
        ((i_remaining_borrow && i_channel_high_last) !=
         (channel_wrap_threshold && i_channel_high_last)) || outside_interval;
endmodule

`default_nettype wire
