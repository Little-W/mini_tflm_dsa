// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按三位分别比较完整操作数，独立归并各组结果形成相等条件。
(* keep_hierarchy = "yes" *)
module parallel_equal #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input wire logic [p_width-1:0] i_b, // 第二个定宽操作数
    output logic o_equal // 所有对应位均相等
);
    localparam int unsigned p_groups = (p_width+2)/3;
    (* keep = 1 *) logic [p_groups-1:0] group_equal;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
        localparam int unsigned p_first = 3*group_index;
        localparam int unsigned p_bits = p_width-p_first < 3 ? p_width-p_first : 3;
        assign group_equal[group_index] = i_a[p_first+:p_bits] == i_b[p_first+:p_bits];
    end
    // 任意确定的不相等位使结果为零，其余含未知位的情况保持未知。
    assign o_equal = &group_equal;
endmodule

`default_nettype wire
