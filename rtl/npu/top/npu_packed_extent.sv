// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算右操作数的分块维度，在配置接收前并行求出定宽取整结果。
// 采用六十四位模加和右移，输出保留三十二位，适配矩阵配置的范围乘法。
module npu_packed_extent #(
    parameter int unsigned p_dimension_width = 32,
    parameter int unsigned p_size = 16,
    parameter int unsigned p_size_shift = 4
) (
    input wire logic [p_dimension_width-1:0] i_dimension, // 原始矩阵维度
    input wire logic i_packed, // 选择分块存储的维度换算
    output logic [31:0] o_extent // 换算后用于范围乘法的维度
);
    logic [31:0] packed_extent;
    if (p_size_shift > 0 && p_size_shift < 32 &&
        p_size == (32'd1 << p_size_shift)) begin : g_power_of_two
        logic [31:0] complete_blocks;
        logic partial_block;
        localparam int unsigned p_groups = (32+5)/6;
        logic [p_groups-1:0] group_all;
        // 完整块数与尾部非零标志并行形成，进位只经过输出需要的高位。
        assign complete_blocks = 32'(64'(i_dimension) >> p_size_shift);
        assign partial_block = (64'(i_dimension) & (64'(p_size)-64'd1)) != 0;
        for (genvar group = 0; group < p_groups; group++) begin : g_increment
            localparam int unsigned p_first = 6*group;
            localparam int unsigned p_bits = 32-p_first < 6 ? 32-p_first : 6;
            (* keep = group < p_groups-1 *) logic all_bits;
            logic carry_in, unused_carry;
            assign all_bits = &complete_blocks[p_first+:p_bits];
            assign group_all[group] = all_bits;
            if (group == 0) begin : g_first
                assign carry_in = partial_block;
            end else begin : g_later
                assign carry_in = partial_block && (&group_all[group-1:0]);
            end
            assign {unused_carry, packed_extent[p_first+:p_bits]} =
                {1'b0, complete_blocks[p_first+:p_bits]}+(p_bits+1)'(carry_in);
        end
    end else begin : g_general_rounding
        logic [63:0] rounded_dimension;
        logic unused_round_carry;
        parallel_prefix_add #(
            .p_width(64), .p_group_width(4), .p_preserve_groups(1'b1)
        ) u_round (
            .i_a(64'(i_dimension)), .i_b(64'(p_size)-64'd1), .i_carry(1'b0),
            .o_sum(rounded_dimension), .o_carry(unused_round_carry)
        );
        assign packed_extent = 32'(rounded_dimension >> p_size_shift);
    end

    // 完整算术表达式保持未知输入的四态传播；确定输入按分组进位计算。
    always_comb begin
        case (^{i_dimension, i_packed})
            1'b0, 1'b1: o_extent = i_packed ? packed_extent : 32'(i_dimension);
            default: o_extent = i_packed ?
                32'((64'(i_dimension)+64'(p_size)-64'd1) >> p_size_shift) : 32'(i_dimension);
        endcase
    end
endmodule

`default_nettype wire
