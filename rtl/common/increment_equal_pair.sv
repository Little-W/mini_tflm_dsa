// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查加一运算中一组相邻结果位与目标位的一致性。
module increment_equal_pair #(
    parameter bit p_first = 1'b0,
    parameter int unsigned p_count = 2
) (
    input  wire logic [2:0] i_a, // 第一个定宽操作数
    input  wire logic [2:0] i_target, // 需要比较的目标值
    output logic o_equal // 定宽运算结果与目标值相等
);
    logic first_equal, second_equal;
    assign first_equal = p_first ? i_a[1] ^ i_target[1] :
        ~((i_a[1] ^ i_target[1]) ^ (i_a[0] & ~i_target[0]));
    assign second_equal = ~((i_a[2] ^ i_target[2]) ^ (i_a[1] & ~i_target[1]));
    assign o_equal = first_equal && (p_count == 1 || second_equal);
endmodule

`default_nettype wire
