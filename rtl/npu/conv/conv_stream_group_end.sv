// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 直接结合通道组边界与各输出格式的覆盖范围，分别准备有效归约及尾部填充的组末标志。
(* keep_hierarchy = "yes" *)
module conv_stream_group_end #(
  parameter int p_lanes = 8,
  parameter int p_narrow_lanes = 8,
  parameter bit p_contiguous = 1'b1
) (
  input wire logic [p_lanes:0] i_group_range, // 当前通道组的逐通道剩余范围
  input wire logic [p_lanes-1:0] i_active_lane, // 各通道处于有效归约范围内
  input wire logic [p_lanes-1:0] i_column_lane, // 各通道处于当前分块列范围内
  input wire logic [p_lanes-1:0] i_word_s8, // 八位格式下缓存字能够覆盖的通道
  input wire logic [p_lanes-1:0] i_word_s16, // 十六位格式下缓存字能够覆盖的通道
  input wire logic i_narrow_output, // 当前输出受总线通道数限制
  input wire logic i_past_active, // 当前输出已经越过有效归约区域
  input wire logic i_word_output, // 当前输出使用缓存数据字
  input wire logic i_input_s16, // 输入样本使用十六位格式
  output logic o_end // 本次输出到达通道组末尾
);
  logic [p_lanes:0] boundary;
  logic [p_lanes-1:0] reference_available;
  logic reference_end;
  assign boundary[0] = !i_group_range[0];
  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_boundary
    assign boundary[lane+1] = i_group_range[lane] && !i_group_range[lane+1];
    assign reference_available[lane] = (!i_narrow_output || lane < p_narrow_lanes) &&
        (i_past_active || (i_group_range[lane] && i_active_lane[lane])) && i_column_lane[lane] &&
        (!i_word_output || (i_input_s16 ? i_word_s16[lane] : i_word_s8[lane]));
  end
  logic [p_lanes:0] reference_selected;
  assign reference_selected[0] = p_contiguous ? !reference_available[0] : !(|reference_available);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_reference_selected
    if (step == p_lanes) begin : g_last
      assign reference_selected[step] = reference_available[step-1];
    end else if (p_contiguous) begin : g_contiguous
      assign reference_selected[step] = reference_available[step-1] && !reference_available[step];
    end else begin : g_general
      assign reference_selected[step] = reference_available[step-1] &&
          !(|reference_available[p_lanes-1:step]);
    end
  end
  assign reference_end = |(reference_selected & boundary);
  if (p_contiguous) begin : g_contiguous
    logic [p_lanes-1:0] base_lane;
    logic [p_lanes:0] boundary_available;
    logic parallel_end;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
      assign base_lane[lane] = (!i_narrow_output || lane < p_narrow_lanes) && i_column_lane[lane] &&
          (!i_word_output || (i_input_s16 ? i_word_s16[lane] : i_word_s8[lane]));
    end
    // 零长度边界已经排除了有效归约通道，填充阶段再检查零号列的可用性。
    assign boundary_available[0] = !i_past_active || !base_lane[0];
    for (genvar step = 1; step <= p_lanes; step++) begin : g_boundary_available
      logic following_available;
      if (step == p_lanes) begin : g_final
        assign following_available = 1'b0;
      end else begin : g_following
        assign following_available = base_lane[step];
      end
      // 组末边界要求下一通道越界，有效归约阶段直接检查前一通道资格。
      assign boundary_available[step] = base_lane[step-1] &&
          (i_past_active ? !following_available : i_active_lane[step-1]);
    end
    conv_group_range_select #(.p_choices(p_lanes+1), .p_width(1)) u_boundary (
      .i_select(boundary), .i_data(boundary_available), .o_data(parallel_end)
    );
    // 确定输入使用边界化简，未知输入保留完整长度选择的逐位传播。
    always_comb begin
      o_end = reference_end;
      case (^{i_group_range, i_active_lane, i_column_lane, i_word_s8, i_word_s16,
               i_narrow_output, i_past_active, i_word_output, i_input_s16})
        1'b0, 1'b1: o_end = parallel_end;
        default: ;
      endcase
    end
  end else begin : g_general
    assign o_end = reference_end;
  end
endmodule

`default_nettype wire
