// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 两个十七位有符号数的差值完整保存为十八位，最高位直接表示次序。
module vector_interval_bound (
  input wire signed [16:0] i_coordinate, i_minimum, i_maximum,
  output wire o_inside
);
  wire signed [17:0] lower_distance, upper_distance;
  assign lower_distance=$signed({i_coordinate[16],i_coordinate})-$signed({i_minimum[16],i_minimum});
  assign upper_distance=$signed({i_coordinate[16],i_coordinate})-$signed({i_maximum[16],i_maximum});
  assign o_inside=!lower_distance[17] && upper_distance[17];
endmodule

`default_nettype wire
