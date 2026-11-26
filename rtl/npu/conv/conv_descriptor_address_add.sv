// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 使用分段进位选择计算描述符地址，未知输入保持分组加法的逐位传播。
module conv_descriptor_address_add #(
  parameter int p_width = 32
) (
  input wire logic [p_width-1:0] i_a, // 已保存的地址基值
  input wire logic [p_width-1:0] i_b, // 本次提交的地址增量
  input wire logic i_carry, // 最低位输入进位
  output logic [p_width-1:0] o_sum // 提交阶段的完整定宽地址
);
  logic [p_width-1:0] arithmetic_sum, unknown_sum;
  logic unused_carry, unused_unknown_carry;
  parallel_prefix_add #(
    .p_width(p_width), .p_group_width(8), .p_preserve_groups(1'b1),
    .p_carry_select_width(16)
  ) u_sum (
    .i_a(i_a), .i_b(i_b), .i_carry(i_carry),
    .o_sum(arithmetic_sum), .o_carry(unused_carry)
  );
  parallel_prefix_add #(.p_width(p_width), .p_group_width(8), .p_preserve_groups(1'b0)) u_unknown (
    .i_a(i_a), .i_b(i_b), .i_carry(i_carry),
    .o_sum(unknown_sum), .o_carry(unused_unknown_carry)
  );
  always_comb begin
    o_sum = unknown_sum;
    case (^{i_a, i_b, i_carry})
      1'b0, 1'b1: o_sum = arithmetic_sum;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
