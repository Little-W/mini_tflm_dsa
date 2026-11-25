// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三位相等比较以六路组合树合并，完整候选字段按固定分组并行检查。
module kernel_candidate_equal #(
    parameter int p_width = 160
) (
    input  wire logic [p_width-1:0] i_current,
    input  wire logic [p_width-1:0] i_saved,
    output logic o_equal
);
    function automatic int compare_levels(input int groups);
        int nodes;
        begin
            compare_levels = 0;
            nodes = groups;
            while (nodes > 1) begin
                nodes = (nodes + 5) / 6;
                compare_levels++;
            end
        end
    endfunction

    localparam int p_groups = (p_width + 2) / 3;
    localparam int p_levels = compare_levels(p_groups);
    logic [p_groups-1:0] level_equal [0:p_levels];

    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_leaf
        logic [2:0] current_bits, saved_bits;
        // 三位相等结果独立保留，后续归并仅处理单比特条件。
        (* keep = 1 *) logic leaf_o_equal;

        assign current_bits = 3'(i_current >> (3*group_index));
        assign saved_bits = 3'(i_saved >> (3*group_index));
        assign leaf_o_equal = current_bits == saved_bits;
        assign level_equal[0][group_index] = leaf_o_equal;
    end

    for (genvar level = 1; level <= p_levels; level++) begin : g_level
        localparam int p_previous_span = 6 ** (level-1);
        localparam int p_current_span = 6 ** level;
        localparam int p_previous_nodes = (p_groups+p_previous_span-1) / p_previous_span;
        localparam int p_current_nodes = (p_groups+p_current_span-1) / p_current_span;

        for (genvar node = 0; node < p_groups; node++) begin : g_node
            if (node < p_current_nodes) begin : g_present
                localparam int p_children = (p_previous_nodes-6*node >= 6) ?
                    6 : p_previous_nodes-6*node;
                logic [5:0] merge_i_equal;
                logic merge_o_equal;

                for (genvar child = 0; child < 6; child++) begin : g_child
                    if (child < p_children) begin : g_present
                        assign merge_i_equal[child] = level_equal[level-1][6*node+child];
                    end else begin : g_padding
                        assign merge_i_equal[child] = 1'b1;
                    end
                end
                if (p_children > 1) begin : g_merge
                    // 第一层归并限制比较范围，后续层与接收控制共同化简。
                    (* keep = (level == 1) *) logic merged_equal;
                    assign merged_equal = &merge_i_equal;
                    assign merge_o_equal = merged_equal;
                end else begin : g_pass
                    assign merge_o_equal = merge_i_equal[0];
                end
                assign level_equal[level][node] = merge_o_equal;
            end else begin : g_padding
                assign level_equal[level][node] = 1'b1;
            end
        end
    end
    assign o_equal = level_equal[p_levels][0];
endmodule

`default_nettype wire
