// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 结合历史列坐标和完整和值比较，生成历史空间位置的回绕条件。
(* keep_hierarchy = "yes" *)
module conv_history_wrap_select (
  input wire logic i_width_nonzero, // 输出图像宽度非零
  input wire logic i_sum_last_equal, // 步进后的坐标等于历史末列坐标
  input wire logic i_last_after, // 当前比较结果位于历史末列之后
  input wire logic i_sum_wrap_equal, // 步进后的坐标等于回绕目标坐标
  input wire logic i_last_col_high, // 历史末列位于当前低位块的上方
  input wire logic i_wrap_after, // 当前比较结果位于回绕目标之后
  output logic o_wrap // 本次位置步进需要回绕
);
  assign o_wrap = i_width_nonzero &&
      ((i_sum_last_equal && !i_last_after) ||
       (i_sum_wrap_equal && (!i_last_col_high || i_wrap_after)));
endmodule

`default_nettype wire
