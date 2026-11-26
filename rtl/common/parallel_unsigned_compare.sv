// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分组比较两个完整无符号操作数，输出小于及相等关系。
module parallel_unsigned_compare #(
    parameter int unsigned p_width = 32,
    parameter bit p_preserve_groups = 1'b0
) (
    input wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input wire logic [p_width-1:0] i_b, // 第二个定宽操作数
    output logic o_less, // 第一个操作数小于第二个操作数
    output logic o_equal // 两个输入操作数相等
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

`ifdef XILINX_FPGA
    // 宽比较使用两段差值，操作数上限保证每段借位独立保存。
    if (p_width >= 24 && p_width <= 46) begin : g_inferred
        logic less_binary, equal_binary;
        unsigned_compare #(.p_width(p_width)) u_compare (
            .i_a(i_a), .i_b(i_b), .o_less(less_binary), .o_equal(equal_binary)
        );
        always_comb begin
            case (^{i_a, i_b})
                1'b0, 1'b1: {o_less, o_equal} = {less_binary, equal_binary};
                default: {o_less, o_equal} = {i_a < i_b, i_a == i_b};
            endcase
        end
    end else
`endif
    if (1) begin : g_parallel
        // 关键路径可保留分组结果，使宽比较按既定层数归并。
        (* keep = p_preserve_groups *) logic [p_levels:0][p_groups-1:0] stage_less, stage_equal;
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
    end

endmodule

`default_nettype wire
