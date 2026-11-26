// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查窗口横纵坐标，十六位低段比较与坐标高位范围检查共同确定有效性。
module vector_window_bounds (
  input wire logic signed [33:0] i_x, // 窗口左上角的有符号列坐标。
  input wire logic signed [33:0] i_y, // 窗口左上角的有符号行坐标。
  input wire logic [15:0] i_width, // 输入图像的列数。
  input wire logic [15:0] i_height, // 输入图像的行数。
  output logic o_in_bounds // 横纵坐标均落在输入图像范围内。
);
  logic [16:0] x_difference, y_difference;
  logic binary_in_bounds;

  // 扩展零位后的最高差值位分别表示列坐标与行坐标小于对应尺寸。
  parallel_prefix_native_differences #(.p_low_width(17), .p_high_width(17)) u_difference (
      .i_low_a({1'b0, i_x[15:0]}), .i_low_b({1'b0, i_width}),
      .i_high_a({1'b0, i_y[15:0]}), .i_high_b({1'b0, i_height}),
      .o_low_difference(x_difference), .o_high_difference(y_difference)
  );
  assign binary_in_bounds = !(|i_x[33:16]) && !(|i_y[33:16]) &&
      x_difference[16] && y_difference[16];
  always_comb begin
    case (^{i_x, i_y, i_width, i_height})
      1'b0, 1'b1: o_in_bounds = binary_in_bounds;
      default: o_in_bounds = i_x >= 0 && i_y >= 0 &&
          i_x < $signed(34'(i_width)) && i_y < $signed(34'(i_height));
    endcase
  end
endmodule

`default_nettype wire
