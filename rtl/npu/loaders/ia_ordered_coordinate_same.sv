// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两个坐标共用偏移量，高位等式只需要低位进位及相邻高位关系。
module ia_ordered_coordinate_same #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_low_width = 4
) (
    input  wire logic [p_width-1:0] i_base_a /* 第一组坐标的基值 */,
    input  wire logic [p_width-1:0] i_base_b /* 第二组坐标的基值 */,
    input  wire logic [p_width-1:0] i_offset /* 两组坐标共用的偏移量 */,
    output logic o_equal /* 两个坐标和去掉低位后相同 */
);
    localparam int unsigned p_high_width = p_width - p_low_width;
    logic [1:0] low_carry;
    logic [2:0] high_equal;
    logic coordinate_equal;

    //! 1. 独立计算低位进位
    //! -------------------

    if (p_low_width > 0) begin : g_low_carry
        logic [1:0][p_low_width-1:0] unused_low_sum;
        assign {low_carry[0], unused_low_sum[0]} =
            {1'b0, i_base_a[p_low_width-1:0]} + {1'b0, i_offset[p_low_width-1:0]};
        assign {low_carry[1], unused_low_sum[1]} =
            {1'b0, i_base_b[p_low_width-1:0]} + {1'b0, i_offset[p_low_width-1:0]};
    end else begin : g_no_low_carry
        assign low_carry = '0;
    end

    //! 2. 合并高位关系
    //! ---------------

    assign high_equal[0] = i_base_a[p_width-1:p_low_width] ==
        i_base_b[p_width-1:p_low_width];
    // 相邻高位只增加一个单位，分组检查逐位翻转关系和进位连续性。
    increment_equal #(
        .p_width(p_high_width), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)
    ) u_a_advanced (
        .i_a(i_base_a[p_width-1:p_low_width]),
        .i_target(i_base_b[p_width-1:p_low_width]),
        .o_equal(high_equal[1])
    );
    increment_equal #(
        .p_width(p_high_width), .p_preserve_pairs(1'b1), .p_reduce_group_width(6)
    ) u_b_advanced (
        .i_a(i_base_b[p_width-1:p_low_width]),
        .i_target(i_base_a[p_width-1:p_low_width]),
        .o_equal(high_equal[2])
    );
    assign coordinate_equal = (low_carry[0] == low_carry[1]) ? high_equal[0] :
        (low_carry[0] ? high_equal[1] : high_equal[2]);

`ifdef SYNTHESIS
    assign o_equal = coordinate_equal;
`else
    logic [1:0][p_width-1:0] mathematical_sum;
    assign mathematical_sum[0] = i_base_a + i_offset;
    assign mathematical_sum[1] = i_base_b + i_offset;
    always_comb begin
        case (^{i_base_a, i_base_b, i_offset})
            1'b0, 1'b1: o_equal = coordinate_equal;
            default: o_equal = mathematical_sum[0][p_width-1:p_low_width] ==
                mathematical_sum[1][p_width-1:p_low_width];
        endcase
    end
`endif
endmodule

`default_nettype wire
