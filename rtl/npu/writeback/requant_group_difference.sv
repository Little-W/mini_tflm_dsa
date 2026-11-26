// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算完整行数与当前组起点之间的定宽差值及最高进位。
(* keep_hierarchy = "yes" *)
module requant_group_difference #(
    parameter bit p_keep_carry = 1'b1 // 输出进位参与后续计算时保留末组传播节点。
) (
    input wire logic [31:0] i_rows, // 需要处理的完整行数
    input wire logic [31:0] i_inverse_start, // 当前组起始行的按位取反值
    output logic [31:0] o_difference, // 完整行数减去当前组起始行的差值
    output logic o_carry // 最高位输出进位
);
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1),
        .p_dsp_split_width(16), .p_keep_carry(p_keep_carry)) u_add (
        .i_a(i_rows), .i_b(i_inverse_start), .i_carry(1'b1),
        .o_sum(o_difference), .o_carry(o_carry)
    );
endmodule

`default_nettype wire
