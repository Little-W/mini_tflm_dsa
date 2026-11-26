// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 用完整请求起点、长度及驻留结束位置检查请求末端是否越界。
(* keep_hierarchy = "yes" *)
module bias_request_end_compare #(
    parameter int unsigned p_count_width = 29
) (
    input  wire logic [p_count_width-1:0] i_base, // 计算起始位置
    input  wire logic [p_count_width-1:0] i_count, // 本次请求包含的元素数量
    input  wire logic [((p_count_width < 1) ? 1 : p_count_width):0] i_end, // 已驻留数据范围的结束位置
    output logic o_outside // 请求或通道超出有效范围
);
    localparam int unsigned p_range_width = ((p_count_width < 1) ? 1 : p_count_width) + 1;
    logic [p_range_width-1:0] range_add_i_a, range_add_i_b;
    logic range_add_i_carry;
    logic [p_range_width-1:0] range_add_o_sum;
    logic range_add_o_carry;
    logic [p_range_width-1:0] request_base, request_count, carry_bits;
    logic unused_high_carry;
    logic [p_range_width-1:0] unused_range_sum;

    assign request_base = {1'b0, i_base};
    assign request_count = {1'b0, i_count};
    assign range_add_i_a = request_base ^ request_count ^ ~i_end;
    assign carry_bits = (request_base & request_count) |
        ((request_base | request_count) & ~i_end);
    assign {unused_high_carry, range_add_i_b} = {carry_bits, 1'b0};
    assign range_add_i_carry = 1'b0;
    assign unused_range_sum = range_add_o_sum;
    assign o_outside = range_add_o_carry;
    // 平衡划分两个原生加法段，最高进位通过高段传播条件并行求出。
    // 未知输入采用分组传播表达式，保持通用仿真及综合仿真的四态语义。
    parallel_prefix_add #(
        .p_width(p_range_width), .p_group_width(8), .p_preserve_groups(1'b1),
        .p_dsp_split_width((p_range_width >= 24 && p_range_width <= 46) ?
            (p_range_width+1)/2 : 0),
        .p_parallel_high_prefix(1'b1), .p_preserve_grouped_unknowns(1'b1)
    ) u_range_add (
        .i_a(range_add_i_a), .i_b(range_add_i_b), .i_carry(range_add_i_carry),
        .o_sum(range_add_o_sum), .o_carry(range_add_o_carry)
    );
endmodule

`default_nettype wire
