// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在窗口准备边沿保存完整目标归约序号，描述符到达时只比较目标字段。
module conv_descriptor_window_target (
  input wire logic i_clk, // 前端工作时钟
  input wire logic i_write, // 当前边沿保存下一窗口的起点和目标
  input wire logic [31:0] i_preparing_reduction, // 正在准备的窗口归约起点
  input wire logic [31:0] i_saved_reduction, // 已保存窗口的归约起点
  input wire logic [32:0] i_step, // 同一配置内固定的有符号模步长
  input wire logic [31:0] i_target, // 当前描述符请求的完整归约序号
  output logic o_equal // 当前描述符与准备目标的完整三十三位比较结果
);
  logic [32:0] target_sum, target_q;
  logic unused_carry, prepared_equal, reference_equal;
  parallel_prefix_add #(
    .p_width(33), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(16),
    .p_dsp_split_width(17), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
  ) u_prepare (
    .i_a({1'b0, i_preparing_reduction}), .i_b(i_step), .i_carry(1'b0),
    .o_sum(target_sum), .o_carry(unused_carry)
  );
  always_ff @(posedge i_clk) begin
    if (i_write) target_q <= target_sum;
  end
  conv_descriptor_match #(.p_width(33), .p_preserve_groups(1'b1)) u_match (
    .i_a(target_q), .i_b({1'b0, i_target}), .o_equal(prepared_equal)
  );
  // 未知输入使用原逐位加法等式，已知字段使用窗口准备结果。
  add_equal #(.p_width(33), .p_preserve_bits(1'b1), .p_keep_bits(1'b0)) u_reference (
    .i_a({1'b0, i_saved_reduction}), .i_b(i_step),
    .i_target({1'b0, i_target}), .i_carry_in(1'b0), .o_equal(reference_equal)
  );
  always_comb begin
    o_equal = reference_equal;
    case (^{i_saved_reduction, i_step, i_target, target_q})
      1'b0, 1'b1: o_equal = prepared_equal;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
