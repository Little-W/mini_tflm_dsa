// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按有效位顺序归并各局部组的小于及相等关系。
module parallel_unsigned_compare_merge #(
    parameter int unsigned p_count = 3
) (
    input wire logic [p_count-1:0] i_less, // 各比较组的小于结果
    input wire logic [p_count-1:0] i_equal, // 各比较位或比较组的相等结果
    output logic o_less, // 第一个操作数小于第二个操作数
    output logic o_equal // 全部比较组均相等
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

`default_nettype wire
