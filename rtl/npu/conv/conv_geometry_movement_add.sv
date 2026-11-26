// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算完整三十二位地址与几何位移之和。
(* keep_hierarchy = "yes" *)
module conv_geometry_movement_add (
  input wire logic [31:0] i_base, // 计算起始位置
  input wire logic [31:0] i_delta, // 本次有符号编码位移
  output logic [31:0] o_sum // 本级加法结果
);
  logic unused_carry;
  // 两个十六位段并行求和，高位各组独立结合低位进位完成结果修正。
  parallel_prefix_add #(
    .p_width(32), .p_group_width(8), .p_preserve_groups(1'b1),
    .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
  ) u_sum (
    .i_a(i_base), .i_b(i_delta), .i_carry(1'b0), .o_sum(o_sum), .o_carry(unused_carry)
  );
endmodule

`default_nettype wire
