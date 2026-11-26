// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算偏置分组的下一地址，并行比较高段的保持值与递增值，保留定宽回绕。
module npu_output_bias_advance #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_count_width = 10
) (
    input wire logic [p_width-1:0] i_base, // 当前偏置分组的起始行号。
    input wire logic [p_count_width-1:0] i_rows, // 当前偏置分组需要推进的行数。
    input wire logic [p_width-1:0] i_bound, // 最后一个偏置分组的起始行号。
    output logic [p_width-1:0] o_sum, // 按地址位宽回绕的下一分组起始行号。
    output logic o_less, // 下一分组起始行号小于最后一组起始行号。
    output logic o_equal // 下一分组起始行号等于最后一组起始行号。
);
    logic [p_width-1:0] complete_sum;
    logic complete_less, complete_equal, unused_complete_carry;
    localparam int unsigned p_complete_groups = (p_width+7)/8;
    logic [p_complete_groups-1:0] complete_group_less, complete_group_equal;
    logic [p_complete_groups-1:0] complete_group_greater;

    // 四态运算保留完整加法器与比较器的未知值传播。
`ifdef SYNTHESIS
    parallel_prefix_add #(
        .p_width(p_width), .p_group_width(4), .p_preserve_groups(1'b0)
    ) u_complete_sum (
        .i_a(i_base), .i_b(p_width'(i_rows)), .i_carry(1'b0),
        .o_sum(complete_sum), .o_carry(unused_complete_carry)
    );
`else
    assign {unused_complete_carry, complete_sum} =
        {1'b0, i_base} + (p_width+1)'(i_rows);
`endif
    for (genvar group=0; group<p_complete_groups; group++) begin : g_complete_bound
        localparam int unsigned p_first = group*8;
        localparam int unsigned p_bits = p_width-p_first<8 ? p_width-p_first : 8;
        assign complete_group_less[group] = complete_sum[p_first+:p_bits] < i_bound[p_first+:p_bits];
        assign complete_group_equal[group] = complete_sum[p_first+:p_bits] == i_bound[p_first+:p_bits];
        assign complete_group_greater[group] = !complete_group_less[group] && !complete_group_equal[group];
    end
    assign complete_less = complete_group_less > complete_group_greater;
    assign complete_equal = &complete_group_equal;

    if (p_count_width < p_width) begin : g_split
        localparam int unsigned p_high_width = p_width-p_count_width;
        logic [p_count_width:0] low_sum;
        logic [p_high_width-1:0] high_increment;
        logic high_less, high_equal, increment_less, increment_equal;
        logic low_less, low_equal;
        logic [p_count_width-1:0] compare_sum, compare_carry;
        logic [p_count_width-1:0] compare_difference;
        logic compare_out;
        logic compare_distance_bit;
        logic selected_less, selected_equal;
        logic [p_width-1:0] selected_sum;

        // 行数仅影响低段，高段预先完成加一，低段进位只参与最终选择。
        assign low_sum = {1'b0, i_base[p_count_width-1:0]} + {1'b0, i_rows};
        for (genvar bit_index=0; bit_index<p_high_width; bit_index++) begin : g_increment
            if (bit_index == 0) begin : g_first
                assign high_increment[bit_index] = ~i_base[p_count_width+bit_index];
            end else begin : g_later
                assign high_increment[bit_index] = i_base[p_count_width+bit_index] ^
                    (&i_base[p_count_width+:bit_index]);
            end
        end
        assign selected_sum = {
            low_sum[p_count_width] ? high_increment : i_base[p_width-1:p_count_width],
            low_sum[p_count_width-1:0]};

        unsigned_compare #(.p_width(p_high_width)) u_high_bound (
            .i_a(i_base[p_width-1:p_count_width]), .i_b(i_bound[p_width-1:p_count_width]),
            .o_less(high_less), .o_equal(high_equal)
        );
        // 各位同时检查相邻边界要求的进位，与前一位实际产生的进位一致。
        // 相邻相等关系直接读取两个高段，不需要等待高段递增结果。
        if (p_high_width > 1) begin : g_equal_multiple
            assign increment_equal =
                (i_base[p_width-1:p_count_width] ^ i_bound[p_width-1:p_count_width]) ==
                {(i_base[p_width-2:p_count_width] & ~i_bound[p_width-2:p_count_width]), 1'b1};
        end else begin : g_equal_single
            assign increment_equal = i_base[p_count_width] ^ i_bound[p_count_width];
        end
        assign increment_less = (&i_base[p_width-1:p_count_width]) ?
            (|i_bound[p_width-1:p_count_width]) : (high_less && !increment_equal);
        // 三个低段操作数先形成和位与进位，范围关系直接由最终进位判断。
        // 低段回绕只翻转距离的最高位，地址加法和范围比较可并行完成。
        assign compare_sum = i_base[p_count_width-1:0] ^ i_rows ^
            ~i_bound[p_count_width-1:0];
        assign compare_carry = (i_base[p_count_width-1:0] & i_rows) |
            (i_base[p_count_width-1:0] & ~i_bound[p_count_width-1:0]) |
            (i_rows & ~i_bound[p_count_width-1:0]);
        if (p_count_width > 1) begin : g_compare_multiple
            assign {compare_out, compare_difference} = {1'b0, compare_sum} +
                {1'b0, compare_carry[p_count_width-2:0], 1'b1};
        end else begin : g_compare_single
            assign {compare_out, compare_difference} = {1'b0, compare_sum} + 2'd1;
        end
        assign compare_distance_bit = compare_out ^ compare_carry[p_count_width-1];
        assign low_less = low_sum[p_count_width] ^ !compare_distance_bit;
        assign low_equal = compare_difference == '0;
        assign selected_less = low_sum[p_count_width] ?
            (increment_less || (increment_equal && low_less)) :
            (high_less || (high_equal && low_less));
        assign selected_equal = low_equal &&
            (low_sum[p_count_width] ? increment_equal : high_equal);
        always_comb begin
            case (^{i_base, i_rows, i_bound})
                1'b0, 1'b1: begin
                    o_sum = selected_sum;
                    o_less = selected_less;
                    o_equal = selected_equal;
                end
                default: begin
                    o_sum = complete_sum;
                    o_less = complete_less;
                    o_equal = complete_equal;
                end
            endcase
        end
    end else begin : g_full_width
        assign o_sum = complete_sum;
        assign o_less = complete_less;
        assign o_equal = complete_equal;
    end
endmodule

`default_nettype wire
