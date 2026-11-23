// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 坐标步进与范围检查并行计算，尺寸始终采用完整十六位无符号范围。
module conv_coordinate_step #(
  parameter int p_width = 35
) (
  input wire logic [p_width-1:0] i_base,
  input wire logic [p_width-1:0] i_delta,
  input wire logic [15:0] i_limit,
  output logic [p_width-1:0] o_sum,
  output logic o_valid
);
  logic [p_width-1:0] coordinate_sum;
  logic unused_coordinate_carry;
  logic [15:0] unused_low_sum;
  logic low_carry;
  logic [15:0] difference_xor, difference_majority;
  logic [16:0] difference_sum;
  logic unused_difference_carry;
  logic high_zero, low_less;

  parallel_prefix_add #(.p_width(p_width), .p_group_width(8), .p_preserve_groups(1'b1)) u_coordinate (
    .i_a(i_base), .i_b(i_delta), .i_carry(1'b0),
    .o_sum(coordinate_sum), .o_carry(unused_coordinate_carry)
  );

  // 低十六位的进位独立求出，高位零值关系只比较相邻输入位的进位一致性。
  parallel_prefix_add #(.p_width(16), .p_group_width(4), .p_preserve_groups(1'b1)) u_low_carry (
    .i_a(i_base[15:0]), .i_b(i_delta[15:0]), .i_carry(1'b0),
    .o_sum(unused_low_sum), .o_carry(low_carry)
  );
  add_equal #(.p_width(p_width-16)) u_high_zero (
    .i_a(i_base[p_width-1:16]), .i_b(i_delta[p_width-1:16]),
    .i_target((p_width-16)'(0)), .i_carry_in(low_carry), .o_equal(high_zero)
  );

  // 两个坐标分量和尺寸的反码先压缩，范围条件不等待完整坐标和值。
  // 扣除尺寸前后的第十六位进位相同，表示模加后的低位小于尺寸。
  assign difference_xor = i_base[15:0] ^ i_delta[15:0] ^ ~i_limit;
  assign difference_majority = (i_base[15:0] & i_delta[15:0]) |
      ((i_base[15:0] | i_delta[15:0]) & ~i_limit);
  parallel_prefix_add #(.p_width(17), .p_group_width(4), .p_preserve_groups(1'b1)) u_difference (
    .i_a({1'b0, difference_xor}), .i_b({difference_majority, 1'b0}), .i_carry(1'b1),
    .o_sum(difference_sum), .o_carry(unused_difference_carry)
  );
  assign low_less = difference_sum[16] == low_carry;

`ifdef SYNTHESIS
  assign o_sum = coordinate_sum;
  assign o_valid = high_zero && low_less;
`else
  logic [p_width-1:0] mathematical_sum;
  assign mathematical_sum = i_base + i_delta;
  // 未知输入沿用定宽加法与无符号比较的事件仿真传播。
  always_comb begin
    case (^{i_base, i_delta, i_limit})
      1'b0, 1'b1: begin
        o_sum = coordinate_sum;
        o_valid = high_zero && low_less;
      end
      default: begin
        o_sum = mathematical_sum;
        o_valid = mathematical_sum < p_width'(i_limit);
      end
    endcase
  end
`endif
endmodule

`default_nettype wire
