// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分组比较已完成存储体数量和接收阈值，部分写入及计数回绕同时参与最终结果。
(* keep_hierarchy = "yes" *)
module fifo_ready_threshold #(
    parameter int unsigned p_width = 6
) (
    input wire logic [p_width-1:0] i_ready, // 当前已经完成写入的存储体数量。
    input wire logic [p_width-1:0] i_threshold, // 当前分组允许的已完成存储体数量上限。
    input wire logic i_partial, // 当前还存在一个尚未完成写入的存储体。
    output logic o_full // 加入当前部分写入后，存储体数量超过接收阈值。
);
    localparam int unsigned p_groups = (p_width+2)/3;
    (* keep = 1 *) logic [p_groups-1:0] group_greater;
    (* keep = 1 *) logic [p_groups-1:0] group_equal;
    (* keep = 1 *) logic ready_all_ones;
    logic [p_groups-1:0] selected_greater;
    logic grouped_full;

    // 三位比较使用独立条件，最高的不相等位段决定完整计数的大小关系。
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = group*3;
        localparam int unsigned p_bits = p_width-p_first < 3 ? p_width-p_first : 3;
        assign group_greater[group] = i_ready[p_first+:p_bits] > i_threshold[p_first+:p_bits];
        assign group_equal[group] = i_ready[p_first+:p_bits] == i_threshold[p_first+:p_bits];
        if (group == p_groups-1) begin : g_highest
            assign selected_greater[group] = group_greater[group];
        end else begin : g_lower
            assign selected_greater[group] = group_greater[group] && (&group_equal[p_groups-1:group+1]);
        end
    end
    assign ready_all_ones = &i_ready;
    assign grouped_full = !(i_partial && ready_all_ones) &&
        ((|selected_greater) || (i_partial && (&group_equal)));

    // 未知输入沿完整关系表达式传播，计数回绕规则与已确定输入相同。
    always_comb begin
        case (^{i_ready, i_threshold, i_partial})
            1'b0, 1'b1: o_full = grouped_full;
            default: o_full = !(i_partial && (&i_ready)) &&
                ((i_ready > i_threshold) || (i_partial && i_ready == i_threshold));
        endcase
    end
endmodule

`default_nettype wire
