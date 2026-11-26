// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查通道组步进后低位坐标是否达到回绕边界。
module conv_channel_wrap_threshold #(
    parameter int unsigned p_width = 5,
    parameter int unsigned p_step = 1
) (
    input  wire logic [p_width-1:0] i_channel_low, // 当前通道坐标的低位部分
    output logic o_wrap // 本次位置步进需要回绕
);
    if (p_step == 0) begin : g_same_channel
        assign o_wrap = 1'b0;
    end else begin : g_advance_channel
        assign o_wrap = i_channel_low > p_width'((1 << p_width)-p_step-1);
    end
endmodule

`default_nettype wire
