// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 分别计算八位数据、十六位数据和补零输出的剩余范围，格式只参与最终选择。
(* keep_hierarchy = "yes" *)
module conv_stream_format_range #(
  parameter int p_lanes = 8
) (
  input wire logic i_first_allowed, // 当前首通道处于有效范围内
  input wire logic [p_lanes-1:0] i_static_lane, // 由列数和通道状态确定的范围
  input wire logic [p_lanes-1:0] i_word_s8, // 缓存字能够提供的八位样本范围
  input wire logic [p_lanes-1:0] i_word_s16, // 缓存字能够提供的十六位样本范围
  input wire logic [p_lanes-1:0] i_after_lane, // 各通道推进一列后的剩余范围
  input wire logic i_word_output, // 本次输出使用缓存数据字
  input wire logic i_input_s16, // 当前输入为十六位有符号样本
  output logic o_after // 当前输出推进后仍处于有效范围内
);
  localparam int p_data_groups = (p_lanes+1)/2;
  localparam int p_padding_groups = (p_lanes+2)/3;
  (* keep = "true" *) logic [p_data_groups-1:0] s8_group, s16_group;
  (* keep = "true" *) logic [p_padding_groups-1:0] padding_group;
  (* keep = "true" *) logic s8_after, s16_after, padding_after;
  logic [p_lanes-1:0] word_lane;
  logic reference_after;
  for (genvar group_index = 0; group_index < p_data_groups; group_index++) begin : g_data
    localparam int p_first = group_index*2;
    localparam int p_bits = p_lanes-p_first < 2 ? p_lanes-p_first : 2;
    assign s8_group[group_index] = &(~(i_static_lane[p_first+:p_bits] &
        i_word_s8[p_first+:p_bits]) | i_after_lane[p_first+:p_bits]);
    assign s16_group[group_index] = &(~(i_static_lane[p_first+:p_bits] &
        i_word_s16[p_first+:p_bits]) | i_after_lane[p_first+:p_bits]);
  end
  for (genvar group_index = 0; group_index < p_padding_groups; group_index++) begin : g_padding
    localparam int p_first = group_index*3;
    localparam int p_bits = p_lanes-p_first < 3 ? p_lanes-p_first : 3;
    assign padding_group[group_index] = &(~i_static_lane[p_first+:p_bits] |
        i_after_lane[p_first+:p_bits]);
  end
  assign s8_after = &s8_group;
  assign s16_after = &s16_group;
  assign padding_after = &padding_group;
  assign word_lane = i_input_s16 ? i_word_s16 : i_word_s8;
  assign reference_after = i_first_allowed &&
      (&(~(i_static_lane & ({p_lanes{!i_word_output}} | word_lane)) | i_after_lane));
  // 确定格式直接选取一位结果，未知格式继续使用逐通道的位合并语义。
  always_comb begin
    o_after = reference_after;
    case (^{i_word_output, i_input_s16})
      1'b0, 1'b1: o_after = i_first_allowed &&
          (i_word_output ? (i_input_s16 ? s16_after : s8_after) : padding_after);
      default: ;
    endcase
  end
endmodule

`default_nettype wire
