// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并坐标上下界比较及跨区间状态，生成坐标有效标志。
(* keep_hierarchy = "yes" *)
module conv_coordinate_range_result (
  input wire logic i_lower_equal, // 当前坐标等于区间下界
  input wire logic i_upper_equal, // 当前坐标等于区间上界
  input wire logic i_lower_before, // 当前坐标相对区间下界的先后比较结果
  input wire logic i_upper_before, // 当前坐标相对区间上界的先后比较结果
  input wire logic i_block_cross, // 坐标区间跨越当前比较块
  output logic o_valid // 当前比较对象有效
);
  assign o_valid = i_block_cross ?
      ((i_lower_equal && !i_lower_before) || (i_upper_equal && i_upper_before)) :
      (i_lower_equal && !i_lower_before && i_upper_before);
endmodule

`default_nettype wire
