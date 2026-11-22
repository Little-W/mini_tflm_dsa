// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分块无符号比较并组合各块结果。
module kernel_count_compare #(
    parameter int p_width = 48,
    parameter int p_chunk_width = 8
) (
    input  wire logic [p_width-1:0] i_lhs,
    input  wire logic [p_width-1:0] i_rhs,
    output logic o_ge
);
    localparam int p_compare_width = p_chunk_width;
    localparam int p_chunks = (p_width + p_compare_width - 1) / p_compare_width;
    localparam int p_leaves = 1 << $clog2(p_chunks);
    // 保留相邻区间的比较节点，完整层次合并时仍按平衡树计算。
    (* keep = 1 *) logic [2*p_leaves-1:1] equal_tree;
    (* keep = 1 *) logic [2*p_leaves-1:1] greater_tree;

    for (genvar part = 0; part < p_leaves; part++) begin : g_compare
        if (part < p_chunks) begin : g_value
            localparam int p_low = part * p_compare_width;
            localparam int p_part_width = ((p_width - p_low) < p_compare_width) ?
                p_width - p_low : p_compare_width;
            assign equal_tree[p_leaves + part] =
                i_lhs[p_low +: p_part_width] == i_rhs[p_low +: p_part_width];
            assign greater_tree[p_leaves + part] =
                i_lhs[p_low +: p_part_width] > i_rhs[p_low +: p_part_width];
        end else begin : g_padding
            assign equal_tree[p_leaves + part] = 1'b1;
            assign greater_tree[p_leaves + part] = 1'b0;
        end
    end
    for (genvar node = 1; node < p_leaves; node++) begin : g_merge
        assign equal_tree[node] = equal_tree[2*node+1] && equal_tree[2*node];
        assign greater_tree[node] = greater_tree[2*node+1] ||
            (equal_tree[2*node+1] && greater_tree[2*node]);
    end
    assign o_ge = greater_tree[1] || equal_tree[1];
endmodule

`default_nettype wire
