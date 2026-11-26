// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分别准备数据输出与补零输出推进后的范围，运行状态只选择已经完成的结果。
(* keep_hierarchy = "yes" *)
module conv_stream_range_after #(
  parameter int p_lanes = 8
) (
  input wire logic i_first_allowed, // 推进前的首通道处于有效范围内
  input wire logic [p_lanes-1:0] i_static_lane, // 由列数和通道状态确定的通道范围
  input wire logic [p_lanes-1:0] i_word_lane, // 当前缓存字能够覆盖的通道范围
  input wire logic [p_lanes-1:0] i_after_lane, // 各通道推进一列后仍处于有效范围内
  input wire logic i_word_output, // 本次输出使用缓存数据字
  output logic o_after // 本次输出推进后仍处于有效范围内
);
  (* keep = "true" *) logic padding_after, data_after;
  logic reference_after;
  localparam int p_data_groups = (p_lanes+1)/2;
  localparam int p_padding_groups = (p_lanes+2)/3;
  (* keep = "true" *) logic [p_data_groups-1:0] data_group;
  (* keep = "true" *) logic [p_padding_groups-1:0] padding_group;
  // 数据输出每两条通道形成一组，完整范围检查保留六个局部输入。
  for (genvar group_index = 0; group_index < p_data_groups; group_index++) begin : g_data
    localparam int p_first = group_index*2;
    localparam int p_bits = p_lanes-p_first < 2 ? p_lanes-p_first : 2;
    assign data_group[group_index] = &(~(i_static_lane[p_first+:p_bits] &
        i_word_lane[p_first+:p_bits]) | i_after_lane[p_first+:p_bits]);
  end
  // 补零输出只检查静态范围，每组三条通道并行归并。
  for (genvar group_index = 0; group_index < p_padding_groups; group_index++) begin : g_padding
    localparam int p_first = group_index*3;
    localparam int p_bits = p_lanes-p_first < 3 ? p_lanes-p_first : 3;
    assign padding_group[group_index] = &(~i_static_lane[p_first+:p_bits] |
        i_after_lane[p_first+:p_bits]);
  end
  assign padding_after = i_first_allowed && (&padding_group);
  assign data_after = i_first_allowed && (&data_group);
  assign reference_after = i_first_allowed &&
      (&(~(i_static_lane & ({p_lanes{!i_word_output}} | i_word_lane)) | i_after_lane));
  // 未知运行状态使用完整范围表达式，确定状态直接选择预先计算的一位结果。
  always_comb begin
    o_after = reference_after;
    case (i_word_output)
      1'b0: o_after = padding_after;
      1'b1: o_after = data_after;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
