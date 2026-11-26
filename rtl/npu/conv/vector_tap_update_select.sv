// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行形成参数初始化、卷积核推进和输出行推进的寄存器更新选择。
// 深度卷积的较晚接收事件只参与最终归并，权重位置与输入纵坐标独立保持。
(* keep_hierarchy = "yes" *)
module vector_tap_update_select (
  input wire vector_engine_control_pkg::state_t i_state, // 当前向量执行状态
  input wire logic i_config_done, // 配置检查已经完成
  input wire logic i_config_error, // 配置检查发现错误
  input wire logic i_dw_advance, // 深度卷积推进卷积核位置
  input wire logic i_tap_last_modulo, // 当前深度卷积位置为最后一个核位置
  input wire logic i_dw_snapshot, // 当前深度卷积输出快照已接收
  input wire logic i_position_more, // 当前通道组仍有后续输出位置
  input wire logic i_output_column_last, // 当前输出位置位于本行末列
  input wire logic i_compute_group_last, // 当前执行组为最后一组
  input wire logic i_global_pool, // 当前任务采用全局池化
  input wire logic i_spatial, // 当前任务采用空间窗口
  input wire logic i_tap_last_wide, // 当前普通空间计算位于最后一个核位置
  output logic [2:0] o_weight_select, // 配置初值、核初值、下一核位置的独热选择
  output logic [2:0] o_y_select // 原始纵坐标、下一行纵坐标、下一核纵坐标的独热选择
);
  (* keep = 1 *) logic dw_advance_allowed, other_advance;
  logic advance;
  logic initialize, output_position;
  logic [2:0] weight_select, y_select;

  //! 1. 并行事件准备
  //! ----------------

  assign dw_advance_allowed = i_state == vector_engine_control_pkg::DW_EXECUTE &&
      !i_tap_last_modulo;
  assign other_advance =
      (i_state == vector_engine_control_pkg::EXECUTE_COMMIT &&
       i_compute_group_last && !i_global_pool && i_spatial && !i_tap_last_wide) ||
      (i_state == vector_engine_control_pkg::TAP_NEXT && !i_tap_last_wide);
  assign advance = other_advance || (dw_advance_allowed && i_dw_advance);
  assign initialize = i_state == vector_engine_control_pkg::OUTPUT_INIT ||
      (i_state == vector_engine_control_pkg::DW_FINISH && i_dw_snapshot);
  assign output_position = i_state == vector_engine_control_pkg::DW_FINISH &&
      i_dw_snapshot && i_position_more;
  assign weight_select[0] = i_state == vector_engine_control_pkg::CHECK_WAIT &&
      i_config_done && !i_config_error;
  assign weight_select[1] = initialize;
  assign weight_select[2] = advance;
  assign y_select[0] = i_state == vector_engine_control_pkg::OUTPUT_INIT ||
      (output_position && !i_output_column_last);
  assign y_select[1] = output_position && i_output_column_last;
  assign y_select[2] = advance;

  //! 2. 输出与四态控制
  //! ------------------

  always_comb begin
    o_weight_select = weight_select;
    o_y_select = y_select;
    case (^{i_state, i_config_done, i_config_error, i_dw_advance,
             i_tap_last_modulo, i_dw_snapshot, i_position_more,
             i_output_column_last, i_compute_group_last, i_global_pool,
             i_spatial, i_tap_last_wide})
      1'b0, 1'b1: begin end
      default: begin
        // 条件含未知位时使用逐分支的过程控制，保持条件不成立时的寄存器保持行为。
        o_weight_select = '0;
        o_y_select = '0;
        case (i_state)
          vector_engine_control_pkg::CHECK_WAIT: if (i_config_done) begin
            if (i_config_error) begin end
            else o_weight_select[0] = 1'b1;
          end
          vector_engine_control_pkg::OUTPUT_INIT: begin
            o_weight_select[1] = 1'b1;
            o_y_select[0] = 1'b1;
          end
          vector_engine_control_pkg::DW_EXECUTE: if (i_dw_advance) begin
            if (i_tap_last_modulo) begin end
            else begin
              o_weight_select[2] = 1'b1;
              o_y_select[2] = 1'b1;
            end
          end
          vector_engine_control_pkg::DW_FINISH: if (i_dw_snapshot) begin
            o_weight_select[1] = 1'b1;
            if (i_position_more) begin
              if (i_output_column_last) o_y_select[1] = 1'b1;
              else o_y_select[0] = 1'b1;
            end
          end
          vector_engine_control_pkg::EXECUTE_COMMIT: begin
            if (!i_compute_group_last) begin end
            else if (i_global_pool) begin end
            else if (i_spatial) begin
              if (i_tap_last_wide) begin end
              else begin
                o_weight_select[2] = 1'b1;
                o_y_select[2] = 1'b1;
              end
            end
          end
          vector_engine_control_pkg::TAP_NEXT: begin
            if (i_tap_last_wide) begin end
            else begin
              o_weight_select[2] = 1'b1;
              o_y_select[2] = 1'b1;
            end
          end
          default: begin end
        endcase
      end
    endcase
  end
endmodule

`default_nettype wire
