// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 无符号操作数直接比较，组合输出小于和相等结果。
module unsigned_compare #(
    parameter int unsigned p_width = 32
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    output logic o_less,
    output logic o_equal
);
    assign o_less = i_a < i_b;
    assign o_equal = i_a == i_b;
endmodule

`default_nettype wire
