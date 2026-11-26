// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 十六位长度的模坐标区间最多经过两个高位分段，端点各自完成范围比较。
(* keep_hierarchy = "yes" *)
module conv_coordinate_range #(
  parameter int p_width = 35
) (
  input wire logic [p_width-1:0] i_base, // 待检查的模坐标。
  input wire logic [p_width-1:0] i_lower, // 有效坐标区间的包含下界。
  input wire logic [p_width-1:0] i_upper, // 有效坐标区间的不包含上界。
  input wire logic i_block_cross, // 区间两端位于不同的高位分段。
  output logic o_valid // 待检查坐标位于有效区间。
);
  localparam int p_high_groups = (p_width - 16 + 2) / 3;
  (* keep = 1 *) logic [1:0][p_high_groups-1:0] high_group_equal;
  logic [1:0] high_equal, low_before;
  logic valid_value;

  for (genvar bound = 0; bound < 2; bound++) begin : g_bound
    logic [p_width-1:0] endpoint;
    assign endpoint = bound == 0 ? i_lower : i_upper;
    for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high
      localparam int p_first = 16 + 3 * group_index;
      localparam int p_bits = p_width - p_first < 3 ? p_width - p_first : 3;
      assign high_group_equal[bound][group_index] =
          i_base[p_first+:p_bits] == endpoint[p_first+:p_bits];
    end
    logic unused_low_equal;
    parallel_unsigned_compare #(.p_width(16)) u_low (
      .i_a(i_base[15:0]), .i_b(endpoint[15:0]),
      .o_less(low_before[bound]), .o_equal(unused_low_equal)
    );
    assign high_equal[bound] = &high_group_equal[bound];
  end
  conv_coordinate_range_result u_result (
    .i_lower_equal(high_equal[0]), .i_upper_equal(high_equal[1]),
    .i_lower_before(low_before[0]), .i_upper_before(low_before[1]),
    .i_block_cross(i_block_cross), .o_valid(valid_value)
  );

  // 未知输入保留关系比较和条件选择的四态语义。
  always_comb begin
    case (^{i_base, i_lower, i_upper, i_block_cross})
      1'b0, 1'b1: o_valid = valid_value;
      default: o_valid = i_block_cross ?
          (((i_base[p_width-1:16] == i_lower[p_width-1:16]) && !(i_base[15:0] < i_lower[15:0])) ||
           ((i_base[p_width-1:16] == i_upper[p_width-1:16]) && (i_base[15:0] < i_upper[15:0]))) :
          ((i_base[p_width-1:16] == i_lower[p_width-1:16]) &&
           !(i_base[15:0] < i_lower[15:0]) && (i_base[15:0] < i_upper[15:0]));
    endcase
  end
endmodule

`default_nettype wire
