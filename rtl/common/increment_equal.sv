// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按相邻位的进位关系并行检查定宽加一结果。
module increment_equal #(
    parameter int unsigned p_width = 16,
    parameter bit p_preserve_pairs = 1'b0, // 保留相邻两位的比较结果，便于独立归并。
    parameter int unsigned p_reduce_group_width = 0 // 分组归并的比较位数，零表示直接归并。
) (
    input  wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input  wire logic [p_width-1:0] i_target, // 需要比较的目标值
    output logic o_equal // 定宽运算结果与目标值相等
);
    localparam int unsigned p_pairs = (p_width+1)/2;
    (* keep = p_preserve_pairs *) logic [p_pairs-1:0] pair_equal;
    for (genvar pair = 0; pair < p_pairs; pair++) begin : g_pair
        localparam int unsigned p_count = p_width-2*pair < 2 ? 1 : 2;
        logic [2:0] a_pair, target_pair;
        for (genvar item = 0; item < 3; item++) begin : g_item
            localparam int p_bit = 2*pair+item-1;
            if (p_bit >= 0 && p_bit < p_width) begin : g_present
                assign a_pair[item] = i_a[p_bit];
                assign target_pair[item] = i_target[p_bit];
            end else begin : g_unused
                assign a_pair[item] = 1'b0;
                assign target_pair[item] = 1'b0;
            end
        end
        increment_equal_pair #(.p_first(pair == 0), .p_count(p_count)) u_pair (
            .i_a(a_pair), .i_target(target_pair), .o_equal(pair_equal[pair])
        );
    end
    if (p_reduce_group_width > 0) begin : g_grouped_reduce
        localparam int unsigned p_groups = (p_pairs+p_reduce_group_width-1)/p_reduce_group_width;
        (* keep = 1 *) logic [p_groups-1:0] group_equal;
        // 各组独立归并相邻位检查，最终仅合并少量分组结果。
        for (genvar group = 0; group < p_groups; group++) begin : g_group
            localparam int unsigned p_first = group*p_reduce_group_width;
            localparam int unsigned p_count = p_pairs-p_first < p_reduce_group_width ?
                p_pairs-p_first : p_reduce_group_width;
            assign group_equal[group] = &pair_equal[p_first+:p_count];
        end
        assign o_equal = &group_equal;
    end else begin : g_direct_reduce
        assign o_equal = &pair_equal;
    end
endmodule

`default_nettype wire
