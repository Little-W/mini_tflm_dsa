// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算历史行坐标加一，各四位段的全一条件直接参与对应结果位。
module conv_history_row_increment (
  input wire logic [15:0] i_row, // 已保存的十六位历史行坐标
  output logic [16:0] o_row, // 包含最高进位的相邻行坐标
  output logic o_carry // 十七位计算的最高输出进位
);
  logic [16:0] reference_row, parallel_row;
  logic reference_carry;
  (* keep = "true" *) logic [3:0] group_all;
  // 四态分组加法保留未知输入传播，确定输入使用并行前缀结果。
  parallel_prefix_add #(.p_width(17), .p_group_width(4)) u_reference (
    .i_a({1'b0, i_row}), .i_b(17'd1), .i_carry(1'b0),
    .o_sum(reference_row), .o_carry(reference_carry)
  );
  for (genvar group_index = 0; group_index < 4; group_index++) begin : g_group
    assign group_all[group_index] = &i_row[group_index*4+:4];
  end
  assign parallel_row[0] = ~i_row[0];
  for (genvar bit_index = 1; bit_index < 16; bit_index++) begin : g_bit
    localparam int p_groups = bit_index / 4;
    localparam int p_remainder = bit_index % 4;
    logic lower_groups_all, local_bits_all;
    if (p_groups == 0) begin : g_first
      assign lower_groups_all = 1'b1;
    end else begin : g_following
      assign lower_groups_all = &group_all[p_groups-1:0];
    end
    if (p_remainder == 0) begin : g_boundary
      assign local_bits_all = 1'b1;
    end else begin : g_local
      assign local_bits_all = &i_row[p_groups*4+:p_remainder];
    end
    assign parallel_row[bit_index] = i_row[bit_index] ^ (lower_groups_all && local_bits_all);
  end
  assign parallel_row[16] = &group_all;
  always_comb begin
    case (^i_row)
      1'b0, 1'b1: begin
        o_row = parallel_row;
        o_carry = 1'b0;
      end
      default: begin
        o_row = reference_row;
        o_carry = reference_carry;
      end
    endcase
  end
endmodule

`default_nettype wire
