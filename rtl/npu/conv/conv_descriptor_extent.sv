// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 描述符归约起点和空间终点的完整范围检查。
module conv_descriptor_extent #(
  parameter int unsigned p_rw = 5,
  localparam int p_row_low_w = p_rw < 32 ? p_rw : 31,
  localparam int p_row_high_w = 32 - p_row_low_w
) (
  input  wire logic [31:0] i_tile_p0,                                    // 描述符空间起点
  input  wire logic [31:0] i_tile_q0,                                    // 描述符归约起点
  input  wire logic [p_rw-1:0] i_tile_rows,                              // 描述符有效行数
  input  wire logic [31:0] i_reduction_len,                              // 当前配置的归约长度
  input  wire logic [31:0] i_position_count,                             // 当前配置的空间位置数量
  input  wire logic [p_row_high_w-1:0] i_position_high_minus_one_q,        // 位置数量高段减一的保存值
  output logic o_tile_rows_in_range,                               // 描述符全部行处于有效范围
  output logic o_tile_q_before_end                                 // 归约起点小于有效归约长度
);

  //! 0. 辅助信号
  //! -------------

  logic [3:0] tile_q_byte_before;
  logic [3:0] tile_q_byte_equal;
  logic tile_q_before_parallel;
  logic unused_tile_q_equal;
  logic tile_q_before_reference;

  //! 1. 检查描述符范围
  //! -------------------

  // 描述符范围比较独立完成，接收资格只组合各范围的一位结果。
  parallel_unsigned_compare #(.p_width(32)) u_tile_q_range (
    .i_a(i_tile_q0), .i_b(i_reduction_len),
    .o_less(tile_q_before_parallel), .o_equal(unused_tile_q_equal)
  );
`ifdef SYNTHESIS
  assign o_tile_q_before_end = tile_q_before_parallel;
`else
  for (genvar byte_index = 0; byte_index < 4; byte_index++) begin : g_tile_q_range
    assign tile_q_byte_before[byte_index] =
      i_tile_q0[byte_index*8 +: 8] < i_reduction_len[byte_index*8 +: 8];
    assign tile_q_byte_equal[byte_index] =
      i_tile_q0[byte_index*8 +: 8] == i_reduction_len[byte_index*8 +: 8];
  end
  assign tile_q_before_reference = tile_q_byte_before[3] ||
    (tile_q_byte_equal[3] && tile_q_byte_before[2]) ||
    ((&tile_q_byte_equal[3:2]) && tile_q_byte_before[1]) ||
    ((&tile_q_byte_equal[3:1]) && tile_q_byte_before[0]);
  always_comb begin
    case (^{i_tile_q0, i_reduction_len})
      1'b0, 1'b1: o_tile_q_before_end = tile_q_before_parallel;
      default: o_tile_q_before_end = tile_q_before_reference;
    endcase
  end
`endif

  if (p_rw < 32) begin : g_tile_row_range
    logic [p_row_low_w:0] row_end_low;
    logic high_before_end, high_at_end, high_before_end_by_one, low_within_end;
    logic high_before_parallel, high_equal_parallel;

    // 描述符低位相加与高位比较并行，末端独立归并五个位条件。
    assign row_end_low = {1'b0, i_tile_p0[p_row_low_w-1:0]} + {1'b0, i_tile_rows};
    parallel_unsigned_compare #(.p_width(p_row_high_w)) u_high_range (
      .i_a(i_tile_p0[31:p_row_low_w]), .i_b(i_position_count[31:p_row_low_w]),
      .o_less(high_before_parallel), .o_equal(high_equal_parallel)
    );
    conv_descriptor_match #(.p_width(p_row_high_w)) u_high_last (
      .i_a(i_tile_p0[31:p_row_low_w]), .i_b(i_position_high_minus_one_q),
      .o_equal(high_before_end_by_one)
    );
`ifdef SYNTHESIS
    assign high_before_end = high_before_parallel;
    assign high_at_end = high_equal_parallel;
`else
    if (p_row_high_w <= 27) begin : g_high_range_tree
      logic [26:0] row_high_a, row_high_b;
      logic [8:0] leaf_before, leaf_equal;
      logic [2:0] group_before, group_equal;
      logic high_before_reference, high_equal_reference;

      // 未知输入保留逐段关系运算的传播范围。
      assign row_high_a = 27'(i_tile_p0[31:p_row_low_w]);
      assign row_high_b = 27'(i_position_count[31:p_row_low_w]);
      for (genvar part = 0; part < 9; part++) begin : g_leaf
        assign leaf_before[part] = row_high_a[3*part +: 3] < row_high_b[3*part +: 3];
        assign leaf_equal[part] = row_high_a[3*part +: 3] == row_high_b[3*part +: 3];
      end
      for (genvar part = 0; part < 3; part++) begin : g_group
        assign group_equal[part] = &leaf_equal[3*part +: 3];
        assign group_before[part] = leaf_before[3*part+2] ||
          (leaf_equal[3*part+2] && leaf_before[3*part+1]) ||
          (leaf_equal[3*part+2] && leaf_equal[3*part+1] && leaf_before[3*part]);
      end
      assign high_equal_reference = &group_equal;
      assign high_before_reference = group_before[2] ||
        (group_equal[2] && group_before[1]) ||
        (group_equal[2] && group_equal[1] && group_before[0]);
      always_comb begin
        case (^{i_tile_p0[31:p_row_low_w], i_position_count[31:p_row_low_w]})
          1'b0, 1'b1: begin
            high_before_end = high_before_parallel;
            high_at_end = high_equal_parallel;
          end
          default: begin
            high_before_end = high_before_reference;
            high_at_end = high_equal_reference;
          end
        endcase
      end
    end else begin : g_high_range_wide
      assign high_before_end = high_before_parallel;
      assign high_at_end = high_equal_parallel;
    end
`endif
    assign low_within_end = row_end_low[p_row_low_w-1:0] <= i_position_count[p_row_low_w-1:0];
    conv_descriptor_row_range_result u_result (
      .i_high_before(high_before_end), .i_high_equal(high_at_end),
      .i_high_last(high_before_end_by_one), .i_low_carry(row_end_low[p_row_low_w]),
      .i_low_within(low_within_end), .o_within(o_tile_rows_in_range)
    );
  end else begin : g_tile_row_range_wide
    assign o_tile_rows_in_range = {1'b0, i_tile_p0} + 33'(i_tile_rows) <= {1'b0, i_position_count};
  end

endmodule

`default_nettype wire
