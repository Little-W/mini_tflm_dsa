// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按相邻位进位关系检查偏置通道，并在最终分组归并时形成带发送资格的结果。
// 普通比较与限定比较共用各组结果，保持定宽加一的完整模运算语义。
module npu_bias_channel_match #(
    parameter int unsigned p_width = 30
) (
    input wire logic [p_width-1:0] i_a, // 偏置基址字序号的按位反码
    input wire logic [p_width-1:0] i_target, // 当前数据流对应的通道序号
    input wire logic i_eligible, // 数据、部分和、控制状态和输出空间满足发送条件
    input wire logic i_mode_eligible, // 当前数据流及地址低位允许采用本通道比较
    output logic o_equal, // 通道序号等于输入值加一的定宽结果
    output logic o_qualified // 通道比较相等且发送资格有效
);
    localparam int unsigned p_pairs = (p_width + 1) / 2;
    localparam int unsigned p_groups = (p_pairs + 5) / 6;
    (* keep = 1 *) logic [p_pairs-1:0] pair_equal;
    (* keep = 1 *) logic [p_groups-1:0] group_equal;

    for (genvar pair = 0; pair < p_pairs; pair++) begin : g_pair
        localparam int unsigned p_count = p_width - 2 * pair < 2 ? 1 : 2;
        logic [2:0] a_pair, target_pair;
        for (genvar item = 0; item < 3; item++) begin : g_item
            localparam int p_bit = 2 * pair + item - 1;
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
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = 6 * group;
        localparam int unsigned p_count = p_pairs - p_first < 6 ? p_pairs - p_first : 6;
        assign group_equal[group] = &pair_equal[p_first +: p_count];
    end
    assign o_equal = &group_equal;
    npu_bias_issue_reduce #(.p_groups(p_groups)) u_issue (
        .i_group_equal(group_equal), .i_eligible(i_eligible),
        .i_mode_eligible(i_mode_eligible), .o_qualified(o_qualified)
    );
endmodule

`default_nettype wire
