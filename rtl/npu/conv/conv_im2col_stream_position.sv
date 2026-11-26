// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 各字段的行推进及内核推进条件分别归并，避免与状态保存值串行计算。
module conv_im2col_stream_position (
  input wire logic i_chunk_end, // 当前传输到达输出行末。
  input wire logic i_row_last, // 当前输出行为描述符最后一行。
  input wire logic i_row_base_valid, // 下一行地址具有可用的增量计算起点。
  input wire logic i_geometry_tile, // 当前分块使用几何预测。
  input wire logic i_row_coordinate_valid, // 下一行坐标具有可用的增量计算起点。
  input wire logic i_past_active, // 当前列已越过有效输出范围。
  input wire logic i_active_after, // 当前传输之后仍有有效输出列。
  input wire logic i_group_end, // 当前传输到达通道组末尾。
  input wire logic i_coordinate_address_valid, // 当前坐标及地址可直接推进。
  output logic o_row_coordinate, // 推进下一行坐标的写入资格。
  output logic o_row_data, // 推进下一行像素和地址的写入资格。
  output logic o_tap_coordinate, // 推进下一核位置坐标的写入资格。
  output logic o_tap_data // 推进下一核位置像素和地址的写入资格。
);
  always_comb begin
    o_row_coordinate = 1'b0;
    o_row_data = 1'b0;
    o_tap_coordinate = 1'b0;
    o_tap_data = 1'b0;
    case (^{i_chunk_end, i_row_last, i_row_base_valid, i_geometry_tile,
             i_row_coordinate_valid, i_past_active, i_active_after,
             i_group_end, i_coordinate_address_valid})
      1'b0, 1'b1: begin
        o_row_coordinate = i_chunk_end && !i_row_last &&
            ((i_row_base_valid && !i_geometry_tile) || i_row_coordinate_valid);
        o_row_data = i_chunk_end && !i_row_last && i_row_base_valid && !i_geometry_tile;
        o_tap_coordinate = !i_chunk_end && !i_past_active && i_active_after && i_group_end;
        o_tap_data = !i_chunk_end && !i_past_active && i_active_after &&
            i_group_end && i_coordinate_address_valid;
      end
      default: begin
        // 未知条件保持过程式分支的选择语义。
        if (i_chunk_end) begin
          if (i_row_last) begin
          end else if (i_row_base_valid && !i_geometry_tile) begin
            o_row_coordinate = 1'b1;
            o_row_data = 1'b1;
          end else if (i_row_coordinate_valid) o_row_coordinate = 1'b1;
        end else if (i_past_active || !i_active_after) begin
        end else if (i_group_end) begin
          o_tap_coordinate = 1'b1;
          if (i_coordinate_address_valid) o_tap_data = 1'b1;
        end
      end
    endcase
  end
endmodule
`default_nettype wire
