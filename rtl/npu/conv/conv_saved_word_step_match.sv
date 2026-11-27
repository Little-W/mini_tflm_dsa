// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 原保存字标签先完成固定步长比较，当前描述符的数据字转发只选择最终匹配结果。
(* keep_hierarchy = "yes" *)
module conv_saved_word_step_match #(
  parameter int unsigned p_width = 29,
  parameter int unsigned p_step = 0
) (
  input wire logic [p_width-1:0] i_a, // 当前运行地址的数据字标签
  input wire logic [p_width-1:0] i_saved, // 运行寄存器保存的数据字标签
  input wire logic i_forward, // 当前描述符转发与运行地址相同的数据字
  output logic o_equal // 固定步长推进后仍能使用所选择的数据字
);
  logic saved_equal, reference_equal;
  logic [p_width-1:0] reference_target;
  conv_word_step_match #(.p_width(p_width), .p_step(p_step)) u_saved (
    .i_a(i_a), .i_target(i_saved), .o_equal(saved_equal)
  );
  assign reference_target = i_forward ? i_a : i_saved;
  add_equal #(.p_width(p_width)) u_reference (
    .i_a(i_a), .i_b(p_width'(p_step)), .i_target(reference_target), .i_carry_in(1'b0),
    .o_equal(reference_equal)
  );
  // 已知标签转发后与当前地址相同，固定步长的模值直接确定匹配关系。
  always_comb begin
    o_equal = reference_equal;
    case (^{i_a, i_saved, i_forward})
      1'b0, 1'b1: o_equal = i_forward ? p_width'(p_step) == '0 : saved_equal;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
