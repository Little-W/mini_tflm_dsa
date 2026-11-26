// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查核列与有符号短步长的模加结果，直接形成卷积核末列比较。
(* keep_hierarchy = "yes" *)
module conv_kernel_step_equal (
  input wire logic [15:0] i_base, // 提交前保存的卷积核列坐标
  input wire logic signed [2:0] i_step, // 本次提交的有符号短步长
  input wire logic [15:0] i_last, // 当前配置保存的卷积核末列
  output logic o_equal // 完整十六位步进结果等于卷积核末列
);
  logic [15:0] reference_sum;
  logic parallel_equal;
  assign reference_sum = i_base + 16'($signed(i_step));
  add_equal #(.p_width(16), .p_preserve_bits(1'b1)) u_match (
    .i_a(i_base), .i_b(16'($signed(i_step))), .i_target(i_last),
    .i_carry_in(1'b0), .o_equal(parallel_equal)
  );
  // 未知坐标或步长保留完整算术结果的四态比较。
  always_comb begin
    o_equal = reference_sum == i_last;
    case (^{i_base, i_step, i_last})
      1'b0, 1'b1: o_equal = parallel_equal;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
