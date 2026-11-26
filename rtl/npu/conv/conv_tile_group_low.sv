// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 通道余量的低段并行形成借位、列数比较和默认长度许可。
module conv_tile_group_low #(
  parameter int unsigned p_width = 5,
  parameter int unsigned p_size = 16
) (
  input  logic [p_width-1:0] i_group,          // 通道组宽度的低段
  input  logic [p_width-1:0] i_first,          // 起始通道的低段
  input  logic [p_width-1:0] i_columns,        // 输入描述符的列数
  output logic               o_borrow,        // 通道余量低段产生借位
  output logic               o_less,          // 通道余量低段小于输入列数
  output logic               o_default_allows // 默认分块长度允许本次范围选择
);

  //! 1. 准备低段范围
  //! -----------------

  // 十六列分块的五位余量保留并行低三位与高两位实现。
  if (p_width == 5 && p_size == 16) begin : g_five
    conv_tile_group_low5 u_low (
      .i_group(i_group), .i_first(i_first), .i_columns(i_columns),
      .o_borrow(o_borrow), .o_less(o_less), .o_default_allows(o_default_allows)
    );
  end else begin : g_general
    logic [p_width-1:0] remaining_low;
    logic unused_low_equal;
    assign remaining_low = i_group - i_first;
    assign o_borrow = i_group < i_first;
    parallel_unsigned_compare #(.p_width(p_width)) u_low (
      .i_a(remaining_low), .i_b(i_columns),
      .o_less(o_less), .o_equal(unused_low_equal)
    );
    assign o_default_allows = (|i_columns) || p_width'(p_size) <= remaining_low;
  end

endmodule

`default_nettype wire
