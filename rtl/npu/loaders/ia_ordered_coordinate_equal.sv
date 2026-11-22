// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较坐标加法结果的高位，结果保留 p_width 位。
module ia_ordered_coordinate_equal #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_low_width = 4
) (
    input  logic [p_width-1:0] i_a,
    input  logic [p_width-1:0] i_b,
    input  logic [p_width-p_low_width-1:0] i_target,
    output logic o_equal
);
    localparam int unsigned p_high_width = p_width - p_low_width;
    logic carry_in;

    //! 1. 计算坐标进位条件
    //! -------------------

    if (p_low_width > 0) begin : g_low_carry
        logic [p_low_width-1:0] unused_low_sum;
        // 只消费低位进位，分组生成条件避免先计算完整低位和值。
        parallel_prefix_add #(
            .p_width(p_low_width), .p_group_width(3), .p_preserve_groups(1'b1)
        ) u_low_carry (
            .i_a(i_a[p_low_width-1:0]), .i_b(i_b[p_low_width-1:0]), .i_carry(1'b0),
            .o_sum(unused_low_sum), .o_carry(carry_in)
        );
    end else begin : g_no_low_carry
        assign carry_in = 1'b0;
    end
    //! 2. 生成坐标比较结果
    //! -------------------

    // 相邻两位的进位一致性并行计算，公共比较器保留每位实际计算结果。
    add_equal #(.p_width(p_high_width)) u_high_equal (
        .i_a(i_a[p_width-1:p_low_width]), .i_b(i_b[p_width-1:p_low_width]),
        .i_target(i_target), .i_carry_in(carry_in), .o_equal(o_equal)
    );
endmodule

`default_nettype wire
