// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较定宽模加结果，各位并行检查相邻输入位的进位一致性。
module add_equal #(
    parameter int unsigned p_width = 32,
    parameter bit p_preserve_bits = 1'b0
) (
    input  wire logic [p_width-1:0] i_a,
    input  wire logic [p_width-1:0] i_b,
    input  wire logic [p_width-1:0] i_target,
    input  wire logic               i_carry_in,
    output logic                   o_equal
);
    (* keep = p_preserve_bits *) logic [p_width-1:0] bit_equal;

    assign bit_equal[0] = ~(i_a[0] ^ i_b[0] ^ i_target[0] ^ i_carry_in);
    for (genvar bit_index = 1; bit_index < p_width; bit_index++) begin : g_bit
        // 目标和值确定低位产生的进位，再与本位所需的进位比较。
        assign bit_equal[bit_index] = ~((i_a[bit_index] ^ i_b[bit_index] ^ i_target[bit_index]) ^
            ((i_a[bit_index-1] & i_b[bit_index-1]) |
             ((i_a[bit_index-1] | i_b[bit_index-1]) & ~i_target[bit_index-1])));
    end
    assign o_equal = &bit_equal;
endmodule

`default_nettype wire
