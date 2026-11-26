// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 五位余量的低三位和高两位并行完成比较，不串接减法结果与宽比较器。
module conv_tile_group_low5 (
  input wire logic [4:0] i_group, // 通道组宽度的低五位
  input wire logic [4:0] i_first, // 起始通道的低五位
  input wire logic [4:0] i_columns, // 输入分块的五位列数
  output logic o_borrow, // 减法产生借位
  output logic o_less, // 差值小于比较目标
  output logic o_default_allows // 默认列数允许本次范围选择
);
  logic [2:0] difference_low;
  logic low_borrow, low_less, unused_low_equal;
  logic [1:0] high_less, high_equal, high_borrow, high_top;
  conv_tile_low_difference u_difference (
    .i_a(i_group[2:0]), .i_b(i_first[2:0]),
    .o_difference(difference_low), .o_borrow(low_borrow)
  );
  parallel_unsigned_compare_leaf #(.p_width(3)) u_low (
    .i_a(difference_low), .i_b(i_columns[2:0]),
    .o_less(low_less), .o_equal(unused_low_equal)
  );
  for (genvar borrow = 0; borrow < 2; borrow++) begin : g_high
    conv_tile_high_compare #(.p_borrow(borrow == 1)) u_compare (
      .i_a(i_group[4:3]), .i_b(i_first[4:3]), .i_target(i_columns[4:3]),
      .o_less(high_less[borrow]), .o_equal(high_equal[borrow]),
      .o_borrow(high_borrow[borrow]), .o_top(high_top[borrow])
    );
  end
  conv_tile_low_less_select u_less (
    .i_high_less(high_less), .i_high_equal(high_equal),
    .i_low_borrow(low_borrow), .i_low_less(low_less), .o_less(o_less)
  );
  conv_tile_low_flag_select u_flags (
    .i_high_borrow(high_borrow), .i_high_top(high_top),
    .i_low_borrow(low_borrow), .i_columns_nonzero(|i_columns),
    .o_borrow(o_borrow), .o_default_allows(o_default_allows)
  );
endmodule

`default_nettype wire
