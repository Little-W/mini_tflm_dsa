// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算描述符加法的两个分段和值，输入进位通过分组传播修正结果。
(* keep_hierarchy = "yes" *)
module conv_descriptor_add #(
  parameter int p_width = 35
) (
  input wire logic [p_width-1:0] i_a, // 第一个定宽操作数
  input wire logic [p_width-1:0] i_b, // 第二个定宽操作数
  input wire logic i_carry, // 最低位输入进位
  output logic [p_width-1:0] o_sum // 保留完整位宽的模加法结果
);
  logic [p_width-1:0] arithmetic_sum;
  if (p_width >= 24 && p_width <= 46) begin : g_parallel
    localparam int p_low_width = p_width <= 39 ? 16 : p_width-23;
    localparam int p_high_width = p_width-p_low_width;
    localparam int p_low_groups = (p_low_width+3)/4;
    localparam int p_high_groups = (p_high_width+3)/4;
    logic [p_low_width:0] low_sum;
    logic [p_high_width:0] high_sum;
    (* keep = "true" *) logic [p_low_groups-1:0] low_propagate;
    (* keep = "true" *) logic [p_high_groups-2:0] high_propagate;
    (* keep = "true" *) logic high_carry;
    parallel_prefix_native_sums #(
      .p_low_width(p_low_width+1), .p_high_width(p_high_width+1)
    ) u_sums (
      .i_low_a({1'b0, i_a[p_low_width-1:0]}), .i_low_b({1'b0, i_b[p_low_width-1:0]}),
      .i_high_a({1'b0, i_a[p_width-1:p_low_width]}),
      .i_high_b({1'b0, i_b[p_width-1:p_low_width]}),
      .o_low_sum(low_sum), .o_high_sum(high_sum)
    );
    // 低段各组的全一条件并行形成，高段进位同时包含分段溢出和输入进位传播。
    for (genvar group_index = 0; group_index < p_low_groups; group_index++) begin : g_low
      localparam int p_first = group_index*4;
      localparam int p_bits = p_low_width-p_first < 4 ? p_low_width-p_first : 4;
      localparam int p_groups = group_index > 0 ? group_index : 1;
      logic [p_groups-1:0] lower_groups;
      assign low_propagate[group_index] = &low_sum[p_first+:p_bits];
      if (group_index == 0) begin : g_first
        assign lower_groups = 1'b1;
      end else begin : g_following
        assign lower_groups = low_propagate[group_index-1:0];
      end
      parallel_prefix_high_group #(.p_bits(p_bits), .p_groups(p_groups)) u_correct (
        .i_groups(lower_groups), .i_sum(low_sum[p_first+:p_bits]),
        .i_carry(i_carry), .i_invert(1'b0), .o_sum(arithmetic_sum[p_first+:p_bits])
      );
    end
    assign high_carry = low_sum[p_low_width] || (i_carry && (&low_propagate));
    // 高段仅修正已经完成的和值，各组独立使用完整低位传播条件。
    for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high
      localparam int p_first = group_index*4;
      localparam int p_bits = p_high_width-p_first < 4 ? p_high_width-p_first : 4;
      localparam int p_groups = group_index > 0 ? group_index : 1;
      logic [p_groups-1:0] lower_groups;
      if (group_index < p_high_groups-1) begin : g_propagation
        assign high_propagate[group_index] = &high_sum[p_first+:p_bits];
      end
      if (group_index == 0) begin : g_first
        assign lower_groups = 1'b1;
      end else begin : g_following
        assign lower_groups = high_propagate[group_index-1:0];
      end
      parallel_prefix_high_group #(.p_bits(p_bits), .p_groups(p_groups)) u_correct (
        .i_groups(lower_groups), .i_sum(high_sum[p_first+:p_bits]),
        .i_carry(high_carry), .i_invert(1'b0), .o_sum(arithmetic_sum[p_low_width+p_first+:p_bits])
      );
    end
  end else begin : g_grouped
    logic unused_carry;
    parallel_prefix_add #(.p_width(p_width), .p_group_width(8), .p_preserve_groups(1'b1)) u_sum (
      .i_a(i_a), .i_b(i_b), .i_carry(i_carry), .o_sum(arithmetic_sum), .o_carry(unused_carry)
    );
  end
  // 未知输入使用完整定宽算术的四态传播规则。
  always_comb begin
    o_sum = i_a + i_b + p_width'(i_carry);
    case (^{i_a, i_b, i_carry})
      1'b0, 1'b1: o_sum = arithmetic_sum;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
