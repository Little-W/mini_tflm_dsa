// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 低位剩余通道数独立检查步长前后的区间。
module conv_channel_outside_interval #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1,
    parameter int unsigned p_lane = 0
) (
    input  wire logic [p_width-1:0] i_remaining_low,
    output logic o_outside
);
    logic before_step;
    if (p_step == 0) begin : g_same_channel
        assign before_step = 1'b0;
    end else begin : g_advance_channel
        assign before_step = i_remaining_low < p_width'(p_step);
    end
    assign o_outside = before_step || (i_remaining_low > p_width'(p_step+p_lane));
endmodule

// 通道低位独立检查当前步长是否越过模计数边界。
module conv_channel_wrap_threshold #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1
) (
    input  wire logic [p_width-1:0] i_channel_low,
    output logic o_wrap
);
    if (p_step == 0) begin : g_same_channel
        assign o_wrap = 1'b0;
    end else begin : g_advance_channel
        assign o_wrap = i_channel_low > p_width'((1 << p_width)-p_step-1);
    end
endmodule

// 各步长与通道共享低位区间和高位状态，形成完整有效范围。
module conv_channel_range_compare #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1,
    parameter int unsigned p_lane = 0
) (
    input  wire logic [p_width-1:0] i_remaining_low,
    input  wire logic [p_width-1:0] i_channel_low,
    input  wire logic i_remaining_borrow,
    input  wire logic i_high_nonzero,
    input  wire logic i_channel_high_last,
    output logic o_allowed
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
