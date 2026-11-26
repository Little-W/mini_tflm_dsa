// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行检查列边界与数据覆盖资格，按通道归并本次传输的分块末列条件。
(* keep_hierarchy = "yes" *)
module conv_stream_chunk_end #(
  parameter int p_lanes = 8,
  parameter int p_narrow_lanes = 8
) (
  input wire logic [p_lanes:0] i_column_lane, // 当前及下一通道位于分块列范围内
  input wire logic [p_lanes-1:0] i_group_lane, // 各通道位于当前通道组范围内
  input wire logic [p_lanes-1:0] i_active_lane, // 各通道位于有效归约范围内
  input wire logic [p_lanes-1:0] i_word_s8, // 八位格式下缓存字能够覆盖的通道
  input wire logic [p_lanes-1:0] i_word_s16, // 十六位格式下缓存字能够覆盖的通道
  input wire logic i_narrow_output, // 当前输出受总线通道数限制
  input wire logic i_past_active, // 当前输出已经越过有效归约区域
  input wire logic i_word_output, // 当前输出使用缓存数据字
  input wire logic i_input_s16, // 输入样本使用十六位格式
  output logic o_end // 本次输出到达分块行末
);
  logic [p_lanes-1:0] static_end, selected_word;
  logic [2:0] reference_format;
  logic complete_end, word_end, reference_end, parallel_end;
  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
    // 每条通道独立完成完整范围资格，输出格式不进入该比较。
    (* keep_hierarchy = "yes" *)
    conv_im2col_chunk_lane #(.p_narrow_lane(lane < p_narrow_lanes)) u_boundary (
      .i_narrow_output(i_narrow_output), .i_column_allowed(i_column_lane[lane]),
      .i_next_column_allowed(i_column_lane[lane+1]), .i_past_active(i_past_active),
      .i_group_allowed(i_group_lane[lane]), .i_active_allowed(i_active_lane[lane]),
      .o_end(static_end[lane])
    );
    assign selected_word[lane] = i_input_s16 ? i_word_s16[lane] : i_word_s8[lane];
  end
  // 缓存字覆盖和完整范围并行归并，是否使用数据字只控制最后一层选择。
  conv_group_range_select #(.p_choices(p_lanes), .p_width(1)) u_word_end (
    .i_select(static_end), .i_data(selected_word), .o_data(word_end)
  );
  assign complete_end = |static_end;
  assign parallel_end = !i_column_lane[0] || (i_word_output ? word_end : complete_end);
  assign reference_format = {|static_end, |(static_end & i_word_s16), |(static_end & i_word_s8)};
  conv_im2col_chunk_end_select u_unknown (
    .i_first_column_allowed(i_column_lane[0]), .i_word_output(i_word_output), .i_input_s16(i_input_s16),
    .i_format_end(reference_format), .o_end(reference_end)
  );
  // 未知输入保留三种输出格式的逐位传播。
  always_comb begin
    o_end = reference_end;
    case (^{i_column_lane, i_group_lane, i_active_lane, i_word_s8, i_word_s16,
             i_narrow_output, i_past_active, i_word_output, i_input_s16})
      1'b0, 1'b1: o_end = parallel_end;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
