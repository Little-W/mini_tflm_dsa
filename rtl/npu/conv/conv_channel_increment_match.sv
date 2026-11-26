// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行比较通道高位加一后的目标值，每两位的进位关系先独立形成匹配结果。
module conv_channel_increment_match #(
    parameter int unsigned p_width = 16,
    parameter bit p_keep_pairs = 1'b1
) (
    input  wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input  wire logic [p_width-1:0] i_target, // 需要比较的目标值
    output logic o_equal // 定宽运算结果与目标值相等
);
    localparam int unsigned p_pairs = (p_width+1)/2;
    (* keep = p_keep_pairs *) logic [p_pairs-1:0] pair_equal;
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
    assign o_equal = &pair_equal;
endmodule

`default_nettype wire
