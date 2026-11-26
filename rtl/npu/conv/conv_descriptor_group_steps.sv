// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 从描述符归约起点并行计算下一组和跨一组位置，保持完整三十三位结果。
module conv_descriptor_group_steps (
  input wire logic [31:0] i_reduction, // 当前描述符的归约起点
  input wire logic [15:0] i_group_channels, // 每个通道组包含的通道数
  output logic [32:0] o_next_group, // 下一通道组的完整归约位置
  output logic [32:0] o_skip_group // 跳过一个通道组的完整归约位置
);
  logic [1:0][32:0] step_result;
  logic [1:0][17:0] low_sum;
  logic [15:0] high_base, high_increment;
  assign high_base = {1'b0, i_reduction[31:17]};
  assign high_increment = high_base + 16'd1;
  // 两种步长只改变低十七位，最高十六位的递增结果由两个候选共用。
  parallel_prefix_native_sums #(.p_low_width(18), .p_high_width(18)) u_low_steps (
    .i_low_a({1'b0, i_reduction[16:0]}), .i_low_b({2'd0, i_group_channels}),
    .i_high_a({1'b0, i_reduction[16:0]}), .i_high_b({1'b0, i_group_channels, 1'b0}),
    .o_low_sum(low_sum[0]), .o_high_sum(low_sum[1])
  );
  for (genvar step = 0; step < 2; step++) begin : g_step
    logic [32:0] increment_value, arithmetic_sum, unknown_sum;
    logic unused_unknown_carry;
    assign increment_value = step == 0 ? {17'd0, i_group_channels} :
      {16'd0, i_group_channels, 1'b0};
    assign arithmetic_sum = {low_sum[step][17] ? high_increment : high_base, low_sum[step][16:0]};
    parallel_prefix_add #(
      .p_width(33), .p_group_width(4), .p_preserve_groups(1'b0),
      .p_carry_select_width(step == 0 ? 0 : 17)
    ) u_unknown (
      .i_a({1'b0, i_reduction}), .i_b(increment_value), .i_carry(1'b0),
      .o_sum(unknown_sum), .o_carry(unused_unknown_carry)
    );
    // 输入含未知位时保留分组加法的逐位传播，确定输入使用分段算术结果。
    always_comb begin
      step_result[step] = unknown_sum;
      case (^{i_reduction, i_group_channels})
        1'b0, 1'b1: step_result[step] = arithmetic_sum;
        default: ;
      endcase
    end
  end
  assign {o_skip_group, o_next_group} = step_result;
endmodule

`default_nettype wire
