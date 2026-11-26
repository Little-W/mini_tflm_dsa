// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 用低位组传播条件和输入进位或借位并行修正本组的各个结果位。
(* keep_hierarchy = "yes" *)
module parallel_prefix_high_group #(
    parameter int unsigned p_bits = 4,
    parameter int unsigned p_groups = 1,
    parameter bit p_borrow_mode = 1'b0 // 为一时按逐位零条件传播借位
) (
    input wire logic [p_groups-1:0] i_groups, // 低位各完整组的进位或借位传播条件
    input wire logic [p_bits-1:0] i_sum, // 本组未修正的和值或差值
    input wire logic i_carry, // 低位段传入的进位或借位
    input wire logic i_invert, // 输入进位编码的极性恢复条件
    output logic [p_bits-1:0] o_sum // 本组完成进位或借位修正的结果
);
    //! 0. 辅助定义
    //! -------------

    logic group_carry;

    //! 1. 输入进位计算
    //! -----------------

    // 加法模式恢复编码进位的极性，减法模式直接使用低段借位。
    // 完整低位组的传播条件同时参与本组修正条件的计算。
    assign group_carry = (p_borrow_mode ? i_carry : (i_carry ^ i_invert)) & (&i_groups);

    //! 2. 输出结果生成
    //! -----------------

    for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
        if (bit_index == 0) begin : g_first
            assign o_sum[bit_index] = i_sum[bit_index] ^ group_carry;
        end else begin : g_following
            if (p_borrow_mode) begin : g_subtract
                assign o_sum[bit_index] = i_sum[bit_index] ^ (group_carry & !(|i_sum[bit_index-1:0]));
            end else begin : g_add
                assign o_sum[bit_index] = i_sum[bit_index] ^ (group_carry & (&i_sum[bit_index-1:0]));
            end
        end
    end
endmodule

`default_nettype wire
