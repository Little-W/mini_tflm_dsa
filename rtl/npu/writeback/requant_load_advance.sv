// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算量化参数装载位置与本次增量之和。
(* keep_hierarchy = "yes" *)
module requant_load_advance (
    input wire logic [31:0] i_offset, // 当前组内或装载偏移
    input wire logic [31:0] i_increment, // 本次装载推进的元素数量
    output logic [31:0] o_offset // 推进后的装载偏移
);
    logic unused_carry;
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1),
        .p_dsp_split_width(16), .p_keep_carry(1'b0)) u_add (
        .i_a(i_offset), .i_b(i_increment), .i_carry(1'b0),
        .o_sum(o_offset), .o_carry(unused_carry)
    );
endmodule

`default_nettype wire
