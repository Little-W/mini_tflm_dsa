// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查当前通道组内指定通道是否超出剩余有效通道区间。
module conv_channel_outside_interval #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1,
    parameter int unsigned p_lane = 0
) (
    input  wire logic [p_width-1:0] i_remaining_low, // 剩余有效通道数量的低位部分
    output logic o_outside // 请求或通道超出有效范围
);
    logic before_step;
    if (p_step == 0) begin : g_same_channel
        assign before_step = 1'b0;
    end else begin : g_advance_channel
        assign before_step = i_remaining_low < p_width'(p_step);
    end
    assign o_outside = before_step || (i_remaining_low > p_width'(p_step+p_lane));
endmodule

`default_nettype wire
