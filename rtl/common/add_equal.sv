// SPDX-License-Identifier: Apache-2.0
// 并行检查各位进位是否一致，比较保留 p_width 位的加法结果。
`default_nettype none
module add_equal #(
    parameter int unsigned p_width = 32,
    parameter bit p_use_lut = 1'b0
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic               o_equal
);
    //! 0. 进位信号
    //! ------------

    logic [p_width-1:0] carry_needed;
    logic [p_width-1:0] carry_generated;
    logic [p_width-1:0] carry_expected;
    logic unused_final_carry;

    //! 1. 计算各位进位条件
    //! --------------------

    // 目标和值确定该位所需进位，同时确定传向下一位的进位。
    assign carry_needed = i_a ^ i_b ^ i_target;
    assign carry_generated = (i_a & i_b) | ((i_a | i_b) & ~i_target);
    assign {unused_final_carry, carry_expected} = {carry_generated, i_carry_in};

    //! 2. 合并逐位比较
    //! ----------------

    // 相邻低位的产生条件与本位所需进位同时比较，保留模加法的溢出行为。
    assign o_equal = (carry_needed == carry_expected);

endmodule
`default_nettype wire
