// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在查询采样边沿保存分组相等关系，采样后归并完整比较结果。
// 输入到寄存器只经过组内比较，输出对应前一个采样边沿的两个操作数。
module conv_cache_registered_equal #(
    parameter int unsigned p_width = 30,
    parameter int unsigned p_group_width = 3
) (
    input wire logic clk, // 查询字段的采样时钟
    input wire logic [p_width-1:0] i_a, // 本次查询的第一个比较操作数
    input wire logic [p_width-1:0] i_b, // 本次查询的第二个比较操作数
    output logic o_equal // 已采样两个操作数的完整相等结果
);
    localparam int unsigned p_groups = (p_width + p_group_width - 1) / p_group_width;
    logic [p_groups-1:0] group_equal;

    // 各组在同一边沿采样，未知位按关系运算符和归约运算的四态语义传播。
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_low = group * p_group_width;
        localparam int unsigned p_bits = p_width - p_low < p_group_width ?
            p_width - p_low : p_group_width;
        always_ff @(posedge clk)
            group_equal[group] <= i_a[p_low+:p_bits] == i_b[p_low+:p_bits];
    end

    assign o_equal = &group_equal;
endmodule

`default_nettype wire
