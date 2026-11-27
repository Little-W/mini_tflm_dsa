// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 计算十六位步长减去三十三位空间跨度，用于配置阶段保存行和卷积核的回绕位移。
// 低段借位与高段两种结果并行形成，保持完整三十三位模减法及未知输入传播。
(* keep_hierarchy = "yes" *)
module conv_runtime_wrap_difference (
  input logic [15:0] i_step, // 沿列推进的无符号步长。
  input logic [32:0] i_span, // 已保存的完整空间跨度。
  output logic [32:0] o_difference // 步长减去跨度的三十三位回绕结果。
);
  (* keep = "true" *) logic [16:0] low_difference;
  (* keep = "true" *) logic [16:0] high_without_borrow;
  logic [16:0] high_with_borrow;
  logic [32:0] complete_difference;

  assign low_difference = {1'b0, i_step} - {1'b0, i_span[15:0]};
  assign high_without_borrow = 17'd0 - i_span[32:16];
  assign high_with_borrow = ~i_span[32:16];
  assign complete_difference = {
    low_difference[16] ? high_with_borrow : high_without_borrow,
    low_difference[15:0]
  };

  // 定宽减法遇到任意未知操作数时，完整结果均为未知值。
  always_comb begin
    case (^{i_step, i_span})
      1'b0, 1'b1: o_difference = complete_difference;
      default: o_difference = 'x;
    endcase
  end
endmodule
`default_nettype wire
