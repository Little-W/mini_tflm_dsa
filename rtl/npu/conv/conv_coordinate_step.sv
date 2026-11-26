// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算坐标步进量和低位范围关系，共享两路十七位普通算术。
module conv_coordinate_step #(
  parameter int p_width = 35
) (
  input wire logic [p_width-1:0] i_base, // 当前坐标的基值。
  input wire logic [p_width-1:0] i_delta, // 待加入坐标的定宽步进量。
  input wire logic [15:0] i_limit, // 有效坐标范围的右端尺寸。
  output logic [p_width-1:0] o_sum, // 步进后的完整定宽坐标。
  output logic o_valid // 步进坐标位于零到尺寸之间的左闭右开区间。
);
  logic [p_width-1:0] four_state_sum;
  logic four_state_valid;
  conv_coordinate_step_four_state #(.p_width(p_width)) u_four_state (
    .i_base(i_base), .i_delta(i_delta), .i_limit(i_limit),
    .o_sum(four_state_sum), .o_valid(four_state_valid)
  );
`ifdef SYNTHESIS
  logic [16:0] low_sum, difference_encoded, difference_sum;
  logic [15:0] difference_xor, difference_majority;
  logic [p_width-17:0] high_zero_sum, high_one_sum;
  logic [p_width-1:0] coordinate_sum;
  localparam int p_upper_bits = p_width-17;
  localparam int p_upper_groups = (p_upper_bits+1)/2;
  (* keep = 1 *) logic upper_valid;
  if (p_upper_bits == 0) begin : g_no_upper_bits
    assign upper_valid = 1'b1;
  end else begin : g_upper_bits
    (* keep = 1 *) logic [p_upper_groups-1:0] group_valid;
    for (genvar group_index = 0; group_index < p_upper_groups; group_index++) begin : g_group
      localparam int p_first = 17+2*group_index;
      localparam int p_bits = p_width-p_first < 2 ? p_width-p_first : 2;
      // 每组最多使用六个原始操作数位，范围条件独立于完整坐标的进位计算。
      conv_coordinate_upper_group #(.p_bits(p_bits)) u_group (
        .i_a(i_base[p_first-1 +: p_bits+1]),
        .i_b(i_delta[p_first-1 +: p_bits+1]), .o_valid(group_valid[group_index])
      );
    end
    assign upper_valid = &group_valid;
  end

  assign difference_xor = i_base[15:0] ^ i_delta[15:0] ^ ~i_limit;
  assign difference_majority = (i_base[15:0] & i_delta[15:0]) |
      ((i_base[15:0] | i_delta[15:0]) & ~i_limit);
  // 输入进位为一的差值采用反码编码，两路普通加法可同时映射为并行算术。
  parallel_prefix_native_sums #(.p_low_width(17), .p_high_width(17)) u_low_arithmetic (
    .i_low_a({1'b0, i_base[15:0]}), .i_low_b({1'b0, i_delta[15:0]}),
    .i_high_a(~{1'b0, difference_xor}), .i_high_b(~{difference_majority, 1'b0}),
    .o_low_sum(low_sum), .o_high_sum(difference_encoded)
  );
  assign difference_sum = ~difference_encoded;
  assign high_zero_sum = i_base[p_width-1:16] + i_delta[p_width-1:16];
  assign high_one_sum = ~(~i_base[p_width-1:16] + ~i_delta[p_width-1:16]);
  assign coordinate_sum = {low_sum[16] ? high_one_sum : high_zero_sum, low_sum[15:0]};
  // 未知值分支保持各输出原有的逐位事件传播；已知输入共用低段进位。
  always_comb begin
    case (^{i_base, i_delta, i_limit})
      1'b0, 1'b1: begin
        o_sum = coordinate_sum;
        // 低段进位同时用于第十六位零值和低段范围，最后只合并一位高段资格。
        o_valid = upper_valid && (low_sum[16] == (i_base[16] ^ i_delta[16])) &&
            (difference_sum[16] == low_sum[16]);
      end
      default: begin
        o_sum = four_state_sum;
        o_valid = four_state_valid;
      end
    endcase
  end
`else
  assign o_sum = four_state_sum;
  assign o_valid = four_state_valid;
`endif
endmodule

`default_nettype wire
