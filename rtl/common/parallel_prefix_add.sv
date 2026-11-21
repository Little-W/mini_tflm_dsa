// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 各组独立求和，组间并行计算前缀进位，保留全部结果位及最终进位。
module parallel_prefix_add #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_group_width = 8,
    parameter bit p_preserve_groups = 1'b0
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic               i_carry,
    output logic [p_width-1:0]      o_sum,
    output logic                    o_carry
);
    localparam int unsigned p_groups = (p_width + p_group_width - 1) / p_group_width;
    logic [p_width-1:0] bit_generate, bit_propagate;
    // 关键实例可保留分组边界，限制综合时将共享前缀重新串接。
    (* keep = p_preserve_groups *) logic [p_groups-1:0] group_generate;
    (* keep = p_preserve_groups *) logic [p_groups-1:0] group_propagate;
    (* keep = p_preserve_groups *) logic [p_groups:0] group_carry;

    assign bit_generate = i_a & i_b;
    assign bit_propagate = i_a | i_b;
    assign group_carry[0] = i_carry;
    assign o_carry = group_carry[p_groups];

    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = p_group_width * group;
        localparam int unsigned p_bits = (p_width - p_first < p_group_width) ? p_width - p_first : p_group_width;
        logic [p_bits-1:0] generate_terms;
        logic unused_local_carry;

        // 组内各进位产生条件并行计算，最高组允许少于配置的组宽。
        for (genvar bit_idx = 0; bit_idx < p_bits; bit_idx++) begin : g_generate
            if (bit_idx == p_bits - 1) begin : g_last
                assign generate_terms[bit_idx] = bit_generate[p_first+bit_idx];
            end else begin : g_lower
                assign generate_terms[bit_idx] = bit_generate[p_first+bit_idx] &
                    (&bit_propagate[p_first+bit_idx+1 +: p_bits-bit_idx-1]);
            end
        end
        assign group_generate[group] = |generate_terms;
        assign group_propagate[group] = &bit_propagate[p_first +: p_bits];
        assign {unused_local_carry, o_sum[p_first +: p_bits]} =
            {1'b0, i_a[p_first +: p_bits]} + {1'b0, i_b[p_first +: p_bits]} +
            (p_bits+1)'(group_carry[group]);
    end

    if (p_preserve_groups) begin : g_balanced_prefix
        localparam int unsigned p_levels = $clog2(p_groups);
        // 每层只合并相邻的等长前缀，保存各层节点以限制进位的组合深度。
        (* keep = 1 *) logic [p_groups-1:0] prefix_generate [p_levels+1];
        (* keep = 1 *) logic [p_groups-1:0] prefix_propagate [p_levels+1];
        assign prefix_generate[0] = group_generate;
        assign prefix_propagate[0] = group_propagate;
        for (genvar level = 0; level < p_levels; level++) begin : g_level
            for (genvar group = 0; group < p_groups; group++) begin : g_node
                if (group >= (1 << level)) begin : g_merge
                    assign prefix_generate[level+1][group] = prefix_generate[level][group] |
                        (prefix_propagate[level][group] & prefix_generate[level][group-(1 << level)]);
                    assign prefix_propagate[level+1][group] = prefix_propagate[level][group] &
                        prefix_propagate[level][group-(1 << level)];
                end else begin : g_pass
                    assign prefix_generate[level+1][group] = prefix_generate[level][group];
                    assign prefix_propagate[level+1][group] = prefix_propagate[level][group];
                end
            end
        end
        for (genvar group = 0; group < p_groups; group++) begin : g_carry
            assign group_carry[group+1] = prefix_generate[p_levels][group] |
                (i_carry & prefix_propagate[p_levels][group]);
        end
    end else begin : g_compact_prefix
        // 每个边界独立归并低位各组的产生条件，输入进位通过整段传播条件进入。
        for (genvar boundary = 0; boundary < p_groups; boundary++) begin : g_prefix
            logic [boundary:0] generate_terms;
            for (genvar term = 0; term <= boundary; term++) begin : g_term
                if (term == boundary) begin : g_last
                    assign generate_terms[term] = group_generate[term];
                end else begin : g_lower
                    assign generate_terms[term] = group_generate[term] &
                        (&group_propagate[term+1 +: boundary-term]);
                end
            end
            assign group_carry[boundary+1] = (|generate_terms) |
                (i_carry & (&group_propagate[0 +: boundary+1]));
        end
    end

endmodule

`default_nettype wire
