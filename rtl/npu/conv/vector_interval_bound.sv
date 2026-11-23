// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 符号位取反后按无符号次序比较，保持左闭右开的坐标区间。
module vector_interval_bound (
  input wire signed [16:0] i_coordinate, i_minimum, i_maximum,
  output wire o_inside
);
  wire lower_less, upper_less;
  wire unused_lower_equal, unused_upper_equal;
  unsigned_compare #(.p_width(17)) u_lower (
      .i_a({~i_coordinate[16],i_coordinate[15:0]}),
      .i_b({~i_minimum[16],i_minimum[15:0]}),
      .o_less(lower_less), .o_equal(unused_lower_equal));
  unsigned_compare #(.p_width(17)) u_upper (
      .i_a({~i_coordinate[16],i_coordinate[15:0]}),
      .i_b({~i_maximum[16],i_maximum[15:0]}),
      .o_less(upper_less), .o_equal(unused_upper_equal));
  assign o_inside=!lower_less && upper_less;
endmodule

`default_nettype wire
