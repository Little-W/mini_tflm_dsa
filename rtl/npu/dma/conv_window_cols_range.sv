// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查请求列数是否处于一至配置最大列数的有效区间。
(* keep_hierarchy = "yes" *)
module conv_window_cols_range #(
  parameter int p_max_cols = 16
) (
  input wire logic [31:0] i_columns, // 请求中的完整列数
  output logic o_valid // 当前比较对象有效
);
  localparam logic [32:0] p_limit = {1'b0, 32'(p_max_cols)};
  localparam int unsigned p_low_width = p_limit == 0 ? 1 : $clog2(p_limit + 33'd1);
  logic high_zero, low_valid;

  // 高位归零和低位上限同时比较，保留完整三十二位无符号范围。
  if (p_low_width < 32) begin : g_high_columns
    assign high_zero = !(|i_columns[31:p_low_width]);
  end else begin : g_full_columns
    assign high_zero = 1'b1;
  end
  assign low_valid = (|i_columns[p_low_width-1:0]) &&
      i_columns[p_low_width-1:0] <= p_low_width'(p_max_cols);
  always_comb begin
    o_valid = high_zero && low_valid;
`ifndef SYNTHESIS
    if ((^i_columns) === 1'bx) o_valid = i_columns > 32'd0 && i_columns <= 32'(p_max_cols);
`endif
  end
endmodule

`default_nettype wire
