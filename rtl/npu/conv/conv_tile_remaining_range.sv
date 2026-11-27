// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 保存窗口的通道余量按高低两段并行检查，默认列数与显式列数共享末级选择。
(* keep_hierarchy = "yes" *)
module conv_tile_remaining_range #(
  parameter int unsigned p_width = 5,
  parameter int unsigned p_size = 16
) (
  input wire logic [16:0] i_remaining, // 保存窗口起点到通道组末尾的有符号余量
  input wire logic [p_width-1:0] i_columns, // 输入描述符的列数，零表示完整分块
  output logic o_fits // 请求列数处于保存窗口的通道组范围内
);
  logic low_less, unused_low_equal;
  localparam int p_high_groups = (16-p_width+5)/6;
  (* keep = 1 *) logic [p_high_groups-1:0] high_group_nonzero;
  (* keep = 1 *) logic high_nonzero, low_covers;
  logic fits;
  parallel_unsigned_compare #(.p_width(p_width), .p_preserve_groups(1'b1)) u_low (
    .i_a(i_remaining[p_width-1:0]), .i_b(i_columns),
    .o_less(low_less), .o_equal(unused_low_equal)
  );
  for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high
    localparam int p_first = p_width+6*group_index;
    localparam int p_bits = 16-p_first < 6 ? 16-p_first : 6;
    assign high_group_nonzero[group_index] = |i_remaining[p_first+:p_bits];
  end
  assign high_nonzero = |high_group_nonzero;
  assign low_covers = i_columns == '0 ?
      p_width'(p_size) <= i_remaining[p_width-1:0] : !low_less;
  assign fits = !i_remaining[16] && (high_nonzero || low_covers);

  // 未知输入使用完整定宽关系，保留比较与条件选择的四态传播。
  always_comb begin
    case (^{i_remaining, i_columns})
      1'b0, 1'b1: o_fits = fits;
      default: o_fits = i_columns == '0 ?
          (!i_remaining[16] && 17'(p_size) <= i_remaining) :
          (!i_remaining[16] && 17'(i_columns) <= i_remaining);
    endcase
  end
endmodule

`default_nettype wire
