// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算配置归约起点加上两倍通道组宽度，保留完整三十三位地址。
// 偶数字节增量保留最低位，低段加法与高段递增并行完成。
module conv_cfg_skip_group (
  input wire logic [31:0] i_reduction, // 配置使用的归约起点
  input wire logic [15:0] i_group_channels, // 单个通道组的宽度
  output logic [32:0] o_result // 跳过一个通道组后的完整位置
);
  logic [16:0] low_sum;
  logic [15:0] high_base, high_increment;
  logic [32:0] arithmetic_sum, reference_sum;
  logic unused_reference_carry;
  assign low_sum = {1'b0, i_reduction[16:1]} + {1'b0, i_group_channels};
  assign high_base = {1'b0, i_reduction[31:17]};
  assign high_increment = high_base + 16'd1;
  assign arithmetic_sum = {
      low_sum[16] ? high_increment : high_base, low_sum[15:0], i_reduction[0]};
  parallel_prefix_add #(.p_width(33), .p_group_width(8), .p_preserve_groups(1'b1)) u_reference (
    .i_a({1'b0, i_reduction}), .i_b({16'd0, i_group_channels, 1'b0}), .i_carry(1'b0),
    .o_sum(reference_sum), .o_carry(unused_reference_carry)
  );
  // 未知输入保持分组进位的逐位传播，已知输入采用两段并行结果。
  always_comb begin
    o_result = reference_sum;
    case (^{i_reduction, i_group_channels})
      1'b0, 1'b1: o_result = arithmetic_sum;
      default: ;
    endcase
  end
endmodule
`default_nettype wire
