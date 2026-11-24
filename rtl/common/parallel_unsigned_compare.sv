// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三位以内的输入直接形成相等关系和最高不同位的次序。
(* keep_hierarchy = "yes" *)
module parallel_unsigned_compare_leaf #(
    parameter int unsigned p_width = 3
) (
    input wire logic [p_width-1:0] i_a, i_b,
    output logic o_less, o_equal
);
    logic [p_width-1:0] less_term;
    for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
        if (bit_index == p_width-1) begin : g_high
            assign less_term[bit_index] = !i_a[bit_index] && i_b[bit_index];
        end else begin : g_low
            assign less_term[bit_index] = !i_a[bit_index] && i_b[bit_index] &&
                (i_a[p_width-1:bit_index+1] == i_b[p_width-1:bit_index+1]);
        end
    end
    assign o_less = |less_term;
    assign o_equal = i_a == i_b;
endmodule

// 最高不相等的分组决定次序，每次归并最多三个分组。
(* keep_hierarchy = "yes" *)
module parallel_unsigned_compare_merge #(
    parameter int unsigned p_count = 3
) (
    input wire logic [p_count-1:0] i_less, i_equal,
    output logic o_less, o_equal
);
    logic [p_count-1:0] less_term;
    for (genvar group_index = 0; group_index < p_count; group_index++) begin : g_group
        if (group_index == p_count-1) begin : g_high
            assign less_term[group_index] = i_less[group_index];
        end else begin : g_low
            assign less_term[group_index] = i_less[group_index] &&
                (&i_equal[p_count-1:group_index+1]);
        end
    end
    assign o_less = |less_term;
    assign o_equal = &i_equal;
endmodule

// 输入按三位并行比较，每层归并最多三个分组，得到完整关系。
(* keep_hierarchy = "yes" *)
module parallel_unsigned_compare #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_a, i_b,
    output logic o_less, o_equal
);
    localparam int unsigned p_groups = (p_width + 2) / 3;
    function automatic integer group_count(input integer level);
        group_count = p_groups;
        for (integer step = 0; step < level; step++)
            group_count = (group_count + 2) / 3;
    endfunction
    function automatic integer merge_levels(input integer count);
        merge_levels = 0;
        while (count > 1) begin
            count = (count + 2) / 3;
            merge_levels++;
        end
    endfunction
    localparam int unsigned p_levels = merge_levels(p_groups);
    logic [p_levels:0][p_groups-1:0] stage_less, stage_equal;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_leaf
        localparam int unsigned p_first = 3 * group_index;
        localparam int unsigned p_bits = p_width-p_first < 3 ? p_width-p_first : 3;
        parallel_unsigned_compare_leaf #(.p_width(p_bits)) u_compare (
            .i_a(i_a[p_first+:p_bits]), .i_b(i_b[p_first+:p_bits]),
            .o_less(stage_less[0][group_index]), .o_equal(stage_equal[0][group_index])
        );
    end
    for (genvar level = 1; level <= p_levels; level++) begin : g_level
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            if (group_index < group_count(level)) begin : g_used
                localparam int unsigned p_first = 3 * group_index;
                localparam int unsigned p_count = group_count(level-1)-p_first < 3 ?
                    group_count(level-1)-p_first : 3;
                parallel_unsigned_compare_merge #(.p_count(p_count)) u_merge (
                    .i_less(stage_less[level-1][p_first+:p_count]),
                    .i_equal(stage_equal[level-1][p_first+:p_count]),
                    .o_less(stage_less[level][group_index]), .o_equal(stage_equal[level][group_index])
                );
            end else begin : g_unused
                assign stage_less[level][group_index] = 1'b0;
                assign stage_equal[level][group_index] = 1'b1;
            end
        end
    end
    // 未知输入采用完整关系运算，保留标准四态比较语义。
    always_comb begin
        case (^{i_a, i_b})
            1'b0, 1'b1: begin
                o_less = stage_less[p_levels][0];
                o_equal = stage_equal[p_levels][0];
            end
            default: begin
                o_less = i_a < i_b;
                o_equal = i_a == i_b;
            end
        endcase
    end
endmodule

`default_nettype wire
