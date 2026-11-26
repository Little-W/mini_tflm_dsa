// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算一个局部无符号操作数组的小于及相等关系。
module parallel_unsigned_compare_leaf #(
    parameter int unsigned p_width = 3
) (
    input wire logic [p_width-1:0] i_a, // 第一个定宽操作数
    input wire logic [p_width-1:0] i_b, // 第二个定宽操作数
    output logic o_less, // 第一个操作数小于第二个操作数
    output logic o_equal // 两个输入操作数相等
);
    logic [p_width-1:0] less_term;
    for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
        if (bit_index == p_width-1) begin : g_high
            assign less_term[bit_index] = !i_a[bit_index] && i_b[bit_index];
        end else begin : g_low
            assign less_term[bit_index] = !i_a[bit_index] && i_b[bit_index] &&
                (i_a[p_width-1:bit_index+1] == i_b[p_width-1:bit_index+1]);
        end
    end
    assign o_less = |less_term;
    assign o_equal = i_a == i_b;
endmodule

`default_nettype wire
