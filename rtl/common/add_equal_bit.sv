// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据相邻两位的进位关系检查当前结果位与目标位是否一致。
module add_equal_bit #(
    parameter bit p_first = 1'b0
) (
    input wire logic [1:0] i_a, // 第一个定宽操作数
    input wire logic [1:0] i_b, // 第二个定宽操作数
    input wire logic [1:0] i_target, // 需要比较的目标值
    input wire logic i_carry_in, // 最低位输入进位
    output logic o_equal // 定宽运算结果与目标值相等
);
    logic required_carry;
    assign required_carry = p_first ? i_carry_in :
        (i_a[0] & i_b[0]) | ((i_a[0] | i_b[0]) & ~i_target[0]);
    assign o_equal = ~(i_a[1] ^ i_b[1] ^ i_target[1] ^ required_carry);
endmodule

`default_nettype wire
