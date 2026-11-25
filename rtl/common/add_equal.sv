// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较定宽模加结果，各位并行检查相邻输入位的进位一致性。
module add_equal #(
    parameter int unsigned p_width = 32,
    parameter bit p_preserve_bits = 1'b0
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic                   o_equal
);
    (* keep = p_preserve_bits *) logic [p_width-1:0] bit_equal;

    if (p_preserve_bits) begin : g_parallel_bits
        localparam int unsigned p_groups = (p_width+5)/6;
        logic [p_groups-1:0] group_equal;
        for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
            logic [1:0] a_pair, b_pair, target_pair;
            assign a_pair[1] = i_a[bit_index];
            assign b_pair[1] = i_b[bit_index];
            assign target_pair[1] = i_target[bit_index];
            if (bit_index == 0) begin : g_first
                assign a_pair[0] = 1'b0;
                assign b_pair[0] = 1'b0;
                assign target_pair[0] = 1'b0;
            end else begin : g_previous
                assign a_pair[0] = i_a[bit_index-1];
                assign b_pair[0] = i_b[bit_index-1];
                assign target_pair[0] = i_target[bit_index-1];
            end
            add_equal_bit #(.p_first(bit_index == 0)) u_bit (
                .i_a(a_pair), .i_b(b_pair), .i_target(target_pair),
                .i_carry_in(i_carry_in), .o_equal(bit_equal[bit_index])
            );
        end
        for (genvar group = 0; group < p_groups; group++) begin : g_group
            localparam int unsigned p_first = 6*group;
            localparam int unsigned p_count = p_width-p_first < 6 ? p_width-p_first : 6;
            add_equal_reduce #(.p_width(p_count)) u_reduce (
                .i_equal(bit_equal[p_first+:p_count]), .o_equal(group_equal[group])
            );
        end
        assign o_equal = &group_equal;
    end else begin : g_combined_bits
        assign bit_equal[0] = ~(i_a[0] ^ i_b[0] ^ i_target[0] ^ i_carry_in);
        for (genvar bit_index = 1; bit_index < p_width; bit_index++) begin : g_bit
            // 目标和值确定低位产生的进位，再与本位所需的进位比较。
            assign bit_equal[bit_index] = ~((i_a[bit_index] ^ i_b[bit_index] ^ i_target[bit_index]) ^
                ((i_a[bit_index-1] & i_b[bit_index-1]) |
                 ((i_a[bit_index-1] | i_b[bit_index-1]) & ~i_target[bit_index-1])));
        end
        assign o_equal = &bit_equal;
    end
endmodule

// 每位比较只读取相邻两位，完整归并在上层并行执行。
module add_equal_bit #(
    parameter bit p_first = 1'b0
) (
    input wire logic [1:0] i_a,
    input wire logic [1:0] i_b,
    input wire logic [1:0] i_target,
    input wire logic i_carry_in,
    output logic o_equal
);
    logic required_carry;
    assign required_carry = p_first ? i_carry_in :
        (i_a[0] & i_b[0]) | ((i_a[0] | i_b[0]) & ~i_target[0]);
    assign o_equal = ~(i_a[1] ^ i_b[1] ^ i_target[1] ^ required_carry);
endmodule

// 分组比较结果各自归并，宽操作数的最终检查保留平衡的组合层次。
module add_equal_reduce #(
    parameter int unsigned p_width = 6
) (
    input wire logic [p_width-1:0] i_equal,
    output logic o_equal
);
    assign o_equal = &i_equal;
endmodule

`default_nettype wire
