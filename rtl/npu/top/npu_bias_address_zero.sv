// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查两种数据流的偏置地址是否为零，模式信号只选择已经完成的结果。
// 地址按四字节元素计算，保留控制器可见位宽的完整模加语义。
module npu_bias_address_zero #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_base, // 控制器可见的偏置字节基址
    input wire logic [31:0] i_ws_channel, // 权重驻留模式的输出列序号
    input wire logic [31:0] i_is_channel, // 输入驻留模式的输出行序号
    input wire logic i_is_mode, // 选择输入驻留模式对应的通道序号
    output logic o_zero // 基址加通道字节偏移后的地址为零
);
    logic [31:0] selected_offset;
    logic reference_zero, binary_zero;
    assign selected_offset = (i_is_mode ? i_is_channel : i_ws_channel) << 2;
    add_equal #(.p_width(p_width), .p_preserve_bits(1'b1), .p_keep_bits(1'b0)) u_reference (
        .i_a(i_base), .i_b(p_width'(selected_offset)), .i_target(p_width'(0)),
        .i_carry_in(1'b0), .o_equal(reference_zero)
    );

    if (p_width > 2 && p_width <= 32) begin : g_channel
        localparam int unsigned p_channel_width = p_width-2;
        (* keep = 1 *) logic ws_equal, is_equal;
        // 地址低两位必须为零，其余位检查通道序号是否等于基址字序号的补码。
        increment_equal #(
            .p_width(p_channel_width), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)
        ) u_ws (
            .i_a(~i_base[p_width-1:2]), .i_target(i_ws_channel[p_channel_width-1:0]),
            .o_equal(ws_equal)
        );
        increment_equal #(
            .p_width(p_channel_width), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)
        ) u_is (
            .i_a(~i_base[p_width-1:2]), .i_target(i_is_channel[p_channel_width-1:0]),
            .o_equal(is_equal)
        );
        assign binary_zero = (i_base[1:0] == 2'b0) && (i_is_mode ? is_equal : ws_equal);
    end else if (p_width <= 2) begin : g_low_address
        assign binary_zero = i_base == '0;
    end else begin : g_wide_address
        assign binary_zero = reference_zero;
    end

    // 未知输入沿逐位进位比较传播，已知输入采用并行的通道检查结果。
    always_comb begin
        case (^{i_base, i_ws_channel, i_is_channel, i_is_mode})
            1'b0, 1'b1: o_zero = binary_zero;
            default: o_zero = reference_zero;
        endcase
    end
endmodule

`default_nettype wire
