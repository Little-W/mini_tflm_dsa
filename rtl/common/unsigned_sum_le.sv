// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 判断两个无符号操作数的完整和值是否不超过上限。
// 三个操作数先形成逐位和与进位，再并行归并各组进位，避免先求和再比较。
module unsigned_sum_le #(
    parameter int unsigned p_width = 16,
    parameter int unsigned p_group_width = 3
) (
    input  wire logic [p_width-1:0] i_a, // 第一个非负加数
    input  wire logic [p_width-1:0] i_b, // 第二个非负加数
    input  wire logic [p_width-1:0] i_limit, // 和值允许达到的最大值
    output logic o_within // 完整和值不超过上限时为一
);
    localparam int unsigned p_groups = (p_width + p_group_width - 1) / p_group_width;
    logic [p_width-1:0] sum_bits, carry_bits, shifted_carry;
    logic [p_width-1:0] bit_generate, bit_propagate;
    (* keep = 1 *) logic [p_groups-1:0] group_generate;
    logic [p_groups-1:0] group_propagate;
    logic [p_groups-1:0] carry_terms;
    logic within_binary;

    // a+b+~limit 小于 2**p_width 时，a+b 不超过 limit。
    assign sum_bits = i_a ^ i_b ^ ~i_limit;
    assign carry_bits = (i_a & i_b) | (i_a & ~i_limit) | (i_b & ~i_limit);
    assign shifted_carry = carry_bits << 1;
    assign bit_generate = sum_bits & shifted_carry;
    assign bit_propagate = sum_bits | shifted_carry;

    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = group * p_group_width;
        localparam int unsigned p_bits = p_width-p_first < p_group_width ?
            p_width-p_first : p_group_width;
        logic [p_bits-1:0] generate_terms;
        (* keep = group > 0 *) logic local_propagate;
        for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
            if (bit_index == p_bits-1) begin : g_last
                assign generate_terms[bit_index] = bit_generate[p_first+bit_index];
            end else begin : g_lower
                assign generate_terms[bit_index] = bit_generate[p_first+bit_index] &
                    (&bit_propagate[p_first+bit_index+1+:p_bits-bit_index-1]);
            end
        end
        assign group_generate[group] = |generate_terms;
        assign local_propagate = &bit_propagate[p_first+:p_bits];
        assign group_propagate[group] = local_propagate;
        if (group == p_groups-1) begin : g_high
            assign carry_terms[group] = group_generate[group];
        end else begin : g_lower
            assign carry_terms[group] = group_generate[group] &
                (&group_propagate[group+1+:p_groups-group-1]);
        end
    end
    assign within_binary = !(carry_bits[p_width-1] | (|carry_terms));

    // 含未知位时保留完整加法和关系比较的四态传播。
    always_comb begin
        case (^{i_a, i_b, i_limit})
            1'b0, 1'b1: o_within = within_binary;
            default: o_within = ({1'b0, i_a} + {1'b0, i_b}) <= {1'b0, i_limit};
        endcase
    end
endmodule

`default_nettype wire
