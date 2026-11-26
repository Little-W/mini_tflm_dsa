// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据执行通道编号计算四字节偏置元素的字节地址，输出保留地址低三十二位。
// 两段和值与进位并行形成，完整输入位宽及未知值传播由接口表达式保持。
module npu_bias_execution_address #(
    parameter int unsigned p_base_width = 32
) (
    input wire logic [p_base_width-1:0] i_base, // 当前偏置张量的首字节地址
    input wire logic [31:0] i_channel, // 当前执行的输出通道编号
    output logic [31:0] o_address // 当前通道偏置元素的字节地址低三十二位
);
    //! 0. 辅助声明
    //! ------------

    localparam int unsigned p_sum_width = p_base_width > 32 ? p_base_width : 32;
    logic [p_sum_width-1:0] address_sum_i_a;
    logic [p_sum_width-1:0] address_sum_i_b;
    logic [p_sum_width-1:0] address_sum_o_sum;
    logic unused_carry;

    //! 1. 地址计算
    //! ------------

    assign address_sum_i_a = p_sum_width'(i_base);
    assign address_sum_i_b = p_sum_width'(i_channel) << 2;

    parallel_prefix_add #(
        .p_width(p_sum_width), .p_group_width(8), .p_preserve_groups(1'b1),
        .p_dsp_split_width((p_sum_width+1)/2), .p_parallel_high_prefix(1'b1),
        .p_keep_carry(1'b0)
    ) u_address_sum (
        .i_a(address_sum_i_a), .i_b(address_sum_i_b),
        .i_carry(1'b0), .o_sum(address_sum_o_sum), .o_carry(unused_carry)
    );

    //! 2. 输出生成
    //! ------------

    // 完整表达式保留窄基址扩展、宽基址截断以及被移出位段的四态语义。
    always_comb begin
        case (^{i_base, i_channel})
            1'b0, 1'b1: o_address = 32'(address_sum_o_sum);
            default: o_address = i_base + (i_channel << 2);
        endcase
    end
endmodule

`default_nettype wire
