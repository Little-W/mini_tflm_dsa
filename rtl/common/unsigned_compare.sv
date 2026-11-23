// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 各字节独立比较，再按最高不相等分组决定完整操作数的次序。
module unsigned_compare #(
    parameter int unsigned p_width = 32
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    output logic o_less,
    output logic o_equal
);
    localparam int unsigned p_groups = (p_width + 7) / 8;
    (* keep = 1 *) logic [p_groups-1:0] group_less, group_equal;
    logic [p_groups-1:0] group_greater;
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = group * 8;
        localparam int unsigned p_bits = p_width-p_first < 8 ? p_width-p_first : 8;
        assign group_less[group] = i_a[p_first+:p_bits] < i_b[p_first+:p_bits];
        assign group_equal[group] = i_a[p_first+:p_bits] == i_b[p_first+:p_bits];
        assign group_greater[group] = !group_less[group] && !group_equal[group];
    end
    // 关系向量使用完整比较，任一分组的未知次序继续传播到输出。
    assign o_less = group_less > group_greater;
    assign o_equal = &group_equal;
endmodule

`default_nettype wire
