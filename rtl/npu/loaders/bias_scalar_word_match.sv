// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较标量偏置模地址所在的数据字与写入字地址，按相邻位关系并行检查和值。
module bias_scalar_word_match #(
    parameter int unsigned p_sum_width = 9,
    parameter int unsigned p_address_width = 8,
    parameter int unsigned p_words_per_read = 2
) (
    input wire logic [p_sum_width-1:0] i_base, // 已保存偏置分组的标量元素基址。
    input wire logic [p_sum_width-1:0] i_index, // 分组内的标量元素索引。
    input wire logic [p_address_width-1:0] i_word_address, // 待比较的物理写入字地址。
    output logic o_equal // 模加结果所在的物理数据字与写入地址相同。
);
    logic [p_sum_width-1:0] scalar_sum;
    logic [p_address_width-1:0] reference_address;
    assign scalar_sum = i_base + i_index;
    assign reference_address = p_address_width'(scalar_sum / p_words_per_read);

    if (p_words_per_read > 0 && (p_words_per_read & (p_words_per_read-1)) == 0) begin : g_binary_words
        localparam int unsigned p_shift = $clog2(p_words_per_read);
        logic equal_binary;
        if (p_shift < p_sum_width) begin : g_address_bits
            localparam int unsigned p_compare_width = p_address_width+p_shift < p_sum_width ?
                p_address_width+p_shift : p_sum_width;
            logic [p_compare_width-1:0] target;
            logic sum_equal, upper_valid;
            if (p_shift > 0) begin : g_low_bits
                logic [p_shift-1:0] low_sum;
                assign low_sum = i_base[p_shift-1:0] + i_index[p_shift-1:0];
                assign target = (p_compare_width'(i_word_address) << p_shift) |
                    p_compare_width'(low_sum);
            end else begin : g_full_word
                assign target = p_compare_width'(i_word_address);
            end
            if (p_address_width > p_sum_width-p_shift) begin : g_upper_bits
                assign upper_valid = !(|i_word_address[p_address_width-1:p_sum_width-p_shift]);
            end else begin : g_no_upper_bits
                assign upper_valid = 1'b1;
            end
            add_equal #(.p_width(p_compare_width), .p_preserve_bits(1'b1)) u_sum_match (
                .i_a(i_base[p_compare_width-1:0]), .i_b(i_index[p_compare_width-1:0]),
                .i_target(target), .i_carry_in(1'b0), .o_equal(sum_equal)
            );
            assign equal_binary = upper_valid && sum_equal;
        end else begin : g_single_address
            assign equal_binary = i_word_address == '0;
        end
        // 未知操作数沿完整加法和除法传播，保持地址相等判断的四态结果。
        always_comb begin
            case (^{i_base, i_index, i_word_address})
                1'b0, 1'b1: o_equal = equal_binary;
                default: o_equal = reference_address == i_word_address;
            endcase
        end
    end else begin : g_general_words
        assign o_equal = reference_address == i_word_address;
    end
endmodule

`default_nettype wire
