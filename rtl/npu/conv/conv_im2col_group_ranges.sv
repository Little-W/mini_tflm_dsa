// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算短通道窗口的配置范围、各起点范围和输出传输后的剩余范围。
// 运行通道与已保存范围共同参与组合计算，外部寄存器统一保存更新结果。
module conv_im2col_group_ranges #(
  parameter int p_lanes = 8,
  parameter int p_narrow_lanes = 8,
  parameter int p_saved_group_lanes = 8,
  parameter bit p_contiguous_chunk = 1'b1
) (
  input wire logic [15:0] i_cfg_group_c, // 待接收配置的每组通道数
  input wire logic [15:0] i_group_c, // 当前配置的每组通道数
  input wire logic [15:0] i_channel, // 当前输出的组内通道坐标
  input wire logic [5:0][15:0] i_channel_source, // 六种范围来源对应的通道坐标
  input wire logic [p_saved_group_lanes:0] i_range, // 已保存的当前组剩余范围
  input wire logic [p_lanes:0] i_active_lane, // 有效归约列的逐通道范围
  input wire logic [p_lanes:0] i_column_lane, // 当前分块列的逐通道范围
  input wire logic [p_lanes-1:0] i_word_lane, // 当前数据字能够提供的通道
  input wire logic [p_lanes:0] i_chunk_selected, // 当前传输长度的独热选择
  input wire logic [p_lanes-1:0] i_chunk_lane, // 当前传输的逐通道资格
  input wire logic i_narrow_output, // 当前输出受总线窄通道数限制
  input wire logic i_word_output_q, // 当前输出使用缓存数据字
  output logic [p_saved_group_lanes:0] o_cfg_range, // 配置接收时需要保存的通道范围
  output logic [5:0][p_saved_group_lanes:0] o_next_range, // 六种起点对应的通道范围
  output logic [p_saved_group_lanes:0] o_transfer_range, // 当前传输完成后的通道范围
  output logic [p_lanes-1:0] o_lane_allowed, // 当前组允许输出的通道
  output logic o_after_chunk // 当前传输后组内仍有剩余通道
);
    localparam int p_lane_compare_width = $clog2(p_saved_group_lanes+1);
    logic [p_lane_compare_width:0] configured_remaining;
    (* keep = "true" *) logic configured_high_equal, configured_high_next_equal, configured_high_last;
    (* keep = "true" *) logic configured_high_nonzero;

    borrow_select_subtract #(.p_width(p_lane_compare_width)) u_configured_remaining (
      .i_a(i_cfg_group_c[p_lane_compare_width-1:0]), .i_b(i_channel[p_lane_compare_width-1:0]),
      .o_difference(configured_remaining)
    );
    conv_group_high_compare #(.p_width(16-p_lane_compare_width)) u_configured_high (
      .i_group(i_cfg_group_c[15:p_lane_compare_width]),
      .i_channel(i_channel[15:p_lane_compare_width]),
      .o_equal(configured_high_equal), .o_next_equal(configured_high_next_equal),
      .o_last(configured_high_last)
    );
    // 低段借位只选择高段相等关系，高段比较与低段减法并行。
    assign configured_high_nonzero = configured_remaining[p_lane_compare_width] ?
        !configured_high_next_equal || configured_high_last : !configured_high_equal;
    // 常量通道边界仅比较低位，高位非零条件由全部通道共用。
    for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_cfg_lane
      conv_group_lane_range #(.p_width(p_lane_compare_width), .p_lane(lane)) u_range (
        .i_high_nonzero(configured_high_nonzero),
        .i_remaining(configured_remaining[p_lane_compare_width-1:0]), .o_allowed(o_cfg_range[lane])
      );
    end
    // 配置及译码来源共用完整剩余数量，流式递增提前形成每种步长的范围。
    for (genvar source = 0; source < 6; source++) begin : g_source
      if (source == 5) begin : g_stream_advance
        localparam int p_range_low_w = $clog2(p_lanes+p_saved_group_lanes+1);
        logic [p_range_low_w:0] remaining;
        (* keep = "true" *) logic remaining_high_equal, remaining_high_next_equal;
        (* keep = "true" *) logic remaining_high_nonzero;
        (* keep = "true" *) logic channel_high_last;
        logic [p_lanes:0] channel_wrap;
        logic [p_saved_group_lanes:0][p_lanes:0] selected_range;
        logic [p_lanes:0][p_saved_group_lanes:0] transfer_range_candidate;
        logic [p_lanes-1:0] transfer_lane_allowed;
        logic [p_lanes:0] transfer_selected;

        // 输出阶段准备组范围，换行事件重新装入行首对应的有效通道。
        for (genvar lane = 0; lane < p_lanes; lane++) begin : g_transfer_lane
          assign transfer_lane_allowed[lane] = (!i_narrow_output || lane < p_narrow_lanes) &&
              i_range[lane] && i_active_lane[lane] && i_column_lane[lane] &&
              (!i_word_output_q || i_word_lane[lane]);
        end
        assign transfer_selected[0] = p_contiguous_chunk ?
            !transfer_lane_allowed[0] : !(|transfer_lane_allowed);
        for (genvar step = 1; step <= p_lanes; step++) begin : g_transfer_step
          if (step == p_lanes) begin : g_last
            assign transfer_selected[step] = transfer_lane_allowed[step-1];
          end else if (p_contiguous_chunk) begin : g_contiguous
            assign transfer_selected[step] = transfer_lane_allowed[step-1] && !transfer_lane_allowed[step];
          end else begin : g_lower
            assign transfer_selected[step] = transfer_lane_allowed[step-1] &&
                !(|transfer_lane_allowed[p_lanes-1:step]);
          end
        end

        // 剩余数量只依赖当前坐标；传输数量不经过宽位加减运算。
        borrow_select_subtract #(.p_width(p_range_low_w)) u_remaining (
          .i_a(i_group_c[p_range_low_w-1:0]), .i_b(i_channel[p_range_low_w-1:0]),
          .o_difference(remaining)
        );
        conv_group_high_compare #(.p_width(16-p_range_low_w)) u_remaining_high (
          .i_group(i_group_c[15:p_range_low_w]), .i_channel(i_channel[15:p_range_low_w]),
          .o_equal(remaining_high_equal), .o_next_equal(remaining_high_next_equal),
          .o_last(channel_high_last)
        );
        assign remaining_high_nonzero = remaining[p_range_low_w] ?
            !remaining_high_next_equal : !remaining_high_equal;
        for (genvar step = 0; step <= p_lanes; step++) begin : g_step
          logic remaining_before_step;
          logic reaches_group_end;
          if (step == 0) begin : g_no_wrap
            assign channel_wrap[step] = 1'b0;
            assign remaining_before_step = 1'b0;
            assign reaches_group_end = !i_range[0];
          end else begin : g_wrap
            assign reaches_group_end = i_range[step-1] && !i_range[step];
            assign channel_wrap[step] = channel_high_last &&
                i_channel[p_range_low_w-1:0] > p_range_low_w'((1<<p_range_low_w)-step-1);
            assign remaining_before_step = remaining[p_range_low_w-1:0] < p_range_low_w'(step);
          end
          for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
            (* keep = "true" *) logic range_allowed;
            (* keep_hierarchy = "yes" *)
            conv_channel_range_compare #(
              .p_width(p_range_low_w), .p_step(step), .p_lane(lane)
            ) u_range (
              .i_remaining_low(remaining[p_range_low_w-1:0]),
              .i_channel_low(i_channel[p_range_low_w-1:0]),
              .i_remaining_borrow(remaining[p_range_low_w]),
              .i_high_nonzero(remaining_high_nonzero),
              .i_channel_high_last(channel_high_last), .o_allowed(range_allowed)
            );
            assign selected_range[lane][step] = i_chunk_selected[step] && range_allowed;
            // 每个固定步长先选择组切换或组内递增，再由当前传输数量选取。
            assign transfer_range_candidate[step][lane] =
                reaches_group_end ? o_next_range[0][lane] : range_allowed;
          end
        end
        // 各步长的完整范围先行计算，传输选择只经过统一的独热归并。
        (* keep_hierarchy = "yes" *)
        conv_group_range_select #(
          .p_choices(p_lanes+1), .p_width(p_saved_group_lanes+1)
        ) u_transfer_range (
          .i_select(transfer_selected), .i_data(transfer_range_candidate),
          .o_data(o_transfer_range)
        );
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_select_lane
          assign o_next_range[source][lane] = |selected_range[lane];
        end
      end else begin : g_direct_range
        (* keep = "true" *) logic [p_saved_group_lanes:0] direct_range;
        assign o_next_range[source] = direct_range;
        logic [p_lane_compare_width:0] remaining;
        (* keep = "true" *) logic high_equal, high_next_equal, high_last;
        (* keep = "true" *) logic high_nonzero;
        borrow_select_subtract #(.p_width(p_lane_compare_width)) u_remaining (
          .i_a(i_group_c[p_lane_compare_width-1:0]),
          .i_b(i_channel_source[source][p_lane_compare_width-1:0]), .o_difference(remaining)
        );
        conv_group_high_compare #(.p_width(16-p_lane_compare_width)) u_high (
          .i_group(i_group_c[15:p_lane_compare_width]),
          .i_channel(i_channel_source[source][15:p_lane_compare_width]),
          .o_equal(high_equal), .o_next_equal(high_next_equal), .o_last(high_last)
        );
        assign high_nonzero = remaining[p_lane_compare_width] ?
            !high_next_equal || high_last : !high_equal;
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
          conv_group_lane_range #(.p_width(p_lane_compare_width), .p_lane(lane)) u_range (
            .i_high_nonzero(high_nonzero), .i_remaining(remaining[p_lane_compare_width-1:0]),
            .o_allowed(direct_range[lane])
          );
        end
      end
    end
    assign o_lane_allowed = i_range[p_lanes-1:0];
    assign o_after_chunk = i_range[0] &&
      (&(~i_chunk_lane | i_range[p_lanes:1]));
endmodule

`default_nettype wire
