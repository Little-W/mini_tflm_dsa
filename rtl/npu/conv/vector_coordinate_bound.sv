// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 有符号坐标与十六位尺寸比较，三个相邻位组并行归并大小关系。
module vector_coordinate_bound (
  input  wire logic signed [33:0] i_coordinate, // 待检查的有符号图像坐标。
  input  wire logic [15:0] i_limit, // 该坐标方向的图像尺寸。
  output logic o_in_bounds // 坐标非负且严格小于图像尺寸。
);
  //! 0. 辅助定义
  //! -----------

  logic [15:0] bit_generate, bit_propagate;
  // 仅保存后级实际使用的分组边界，使十六位比较保持并行归并结构。
  (* keep = 1 *) logic [5:0] group_generate;
  logic [5:0] group_propagate;
  (* keep = 1 *) logic [1:0] half_generate;
  logic [1:0] half_propagate;
  logic coordinate_high_zero, coordinate_low_less;

  //! 1. 并行比较坐标与尺寸
  //! -----------------------

  assign bit_generate = ~i_coordinate[15:0] & i_limit;
  assign bit_propagate = ~i_coordinate[15:0] | i_limit;
  for (genvar group_index = 0; group_index < 6; group_index++) begin : g_group
    localparam int p_low = 3 * group_index;
    localparam int p_bits = group_index == 5 ? 1 : 3;
    logic [p_bits-1:0] generate_terms;

    for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
      if (bit_index == p_bits-1) begin : g_high
        assign generate_terms[bit_index] = bit_generate[p_low+bit_index];
      end else begin : g_low
        assign generate_terms[bit_index] = bit_generate[p_low+bit_index] &&
            (&bit_propagate[p_low+bit_index+1 +: p_bits-bit_index-1]);
      end
    end
    assign group_generate[group_index] = |generate_terms;
    if (group_index > 0) begin : g_propagate_boundary
      (* keep = 1 *) logic propagate_value;
      assign propagate_value = &bit_propagate[p_low +: p_bits];
      assign group_propagate[group_index] = propagate_value;
    end else begin : g_first_propagate
      assign group_propagate[group_index] = &bit_propagate[p_low +: p_bits];
    end
  end
  for (genvar half_index = 0; half_index < 2; half_index++) begin : g_half
    localparam int p_low = 3 * half_index;
    assign half_generate[half_index] = group_generate[p_low+2] ||
        (group_propagate[p_low+2] && group_generate[p_low+1]) ||
        (group_propagate[p_low+2] && group_propagate[p_low+1] && group_generate[p_low]);
    assign half_propagate[half_index] = &group_propagate[p_low +: 3];
  end
  assign coordinate_low_less = half_generate[1] || (half_propagate[1] && half_generate[0]);
  assign coordinate_high_zero = i_coordinate[33:16] == 18'd0;
  assign o_in_bounds = coordinate_high_zero && coordinate_low_less;
endmodule

`default_nettype wire
