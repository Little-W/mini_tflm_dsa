// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较当前字标签按固定步长推进后的目标值，零步长及相邻字采用分组相等条件。
module conv_word_step_match #(
  parameter int unsigned p_width = 29,
  parameter int unsigned p_step = 0
) (
  input wire logic [p_width-1:0] i_a, // 当前数据字标签
  input wire logic [p_width-1:0] i_target, // 需要命中的保存字标签
  output logic o_equal // 推进后的字标签与目标相等
);
  logic direct_equal, grouped_equal;
  // 四态输入保留完整加法匹配的相邻位进位关系。
  add_equal #(.p_width(p_width)) u_direct (
    .i_a(i_a), .i_b(p_width'(p_step)), .i_target(i_target), .i_carry_in(1'b0),
    .o_equal(direct_equal)
  );
  if (p_step == 0) begin : g_current
    conv_descriptor_match #(.p_width(p_width), .p_preserve_groups(1'b1)) u_match (
      .i_a(i_a), .i_b(i_target), .o_equal(grouped_equal)
    );
  end else if (p_step == 1) begin : g_next
    conv_channel_increment_match #(.p_width(p_width)) u_match (
      .i_a(i_a), .i_target(i_target), .o_equal(grouped_equal)
    );
  end else if (p_step == 2 && p_width > 1) begin : g_pair
    logic high_equal;
    conv_channel_increment_match #(.p_width(p_width-1), .p_keep_pairs(1'b0)) u_match (
      .i_a(i_a[p_width-1:1]), .i_target(i_target[p_width-1:1]), .o_equal(high_equal)
    );
    assign grouped_equal = high_equal && (i_a[0] == i_target[0]);
  end else begin : g_other
    assign grouped_equal = direct_equal;
  end
  always_comb begin
    o_equal = direct_equal;
    case (^{i_a, i_target})
      1'b0, 1'b1: o_equal = grouped_equal;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
