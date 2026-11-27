// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 保存卷积配置、分块位置、输入坐标和地址生成阶段的数据。
// 描述符接收与输出传输保持各字段的既定写入优先级，停顿期间保留运行数据。
module conv_im2col_runtime_registers #(
  parameter int p_size = 16,
  parameter int p_slot_width = 3,
  parameter int p_count_width = $clog2(p_size+1),
  parameter int p_chunk_width = 2,
  parameter int p_coord_width = 35,
  parameter int p_read_width = 32,
  parameter int p_word_shift = 2,
  parameter int p_row_high_width = 27,
  parameter int p_cache_sets = 128,
  parameter int p_cache_ways = 2,
  parameter int p_saved_group_lanes = 4,
  parameter bit p_register_descriptor = 1'b0,
  parameter int p_prepared_tile_width = 458+2*p_coord_width+3*p_count_width+p_slot_width+p_saved_group_lanes-p_word_shift
) (
  input wire logic clk, // 寄存器更新时钟。
  input wire logic rst_n, // 低有效异步复位。
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前前端运行状态。
  input wire logic i_descriptor_check, // 当前周期保存已提交描述符的首字和填充结果。
  input wire logic [1:0][32:0] i_initial_group, // 配置准备阶段计算的连续分组和跨组位置。
  input wire logic [3:0] i_stream_update, // 行与卷积核推进时的坐标和地址写入资格。
  input wire logic [1:0][31:0] i_group_payload, // 当前卷积核位置和输出行需要保存的通道组地址。
  input wire logic [1:0][p_coord_width-1:0] i_next_row_coordinate, // 下一输出行起点的输入列、行坐标。
  input wire logic [1:0][31:0] i_decode_advance, // 除法解码的下一被除位置和下一余数。
  input wire logic [1:0][31:0] i_fast_coordinate, // 历史快速解码得到的输出列、行坐标。
  input wire logic [1:0][32:0] i_wrap_pixel_sum, // 输出行和卷积核换行需要保存的像素位移。
  input wire logic i_active_after_chunk, // 当前传输之后仍有有效输出列。
  input wire logic [31:0] i_addr, // 当前请求的字节地址。
  input wire logic i_address_position_valid, // 当前坐标和归约位置位于有效输入范围。
  input wire logic i_cache_hint_pending, // 缓存仍在等待预测提示。
  input wire logic [p_read_width-1:0] i_cache_rsp_data, // 缓存返回的当前数据字。
  input wire conv_im2col_pkg::conv_cfg_t i_cfg, // 待接收的卷积配置。
  input wire logic [63:0] i_cfg_input_bytes, // 计算得到的输入张量字节数。
  input wire logic i_cfg_ok, // 配置检查通过。
  input wire logic [31:0] i_cfg_positions, // 计算得到的输出位置总数。
  input wire logic [2:0] i_cfg_prepare_phase, // 配置计算和检查阶段。
  input wire logic i_cfg_ready, // 新卷积配置可被接收。
  input wire logic [31:0] i_cfg_red, // 计算得到的归约长度。
  input wire logic [31:0] i_cfg_sched_groups, // 待保存的调度通道组数。
  input wire logic i_cfg_valid, // 新卷积配置有效。
  input wire logic [31:0] i_channel_addr, // 当前输入位置的完整通道字节地址。
  input wire logic [p_chunk_width-1:0] i_chunk_count, // 当前输出传输包含的列数。
  input wire logic i_chunk_reaches_end, // 当前传输到达输出行末。
  input wire logic i_committing_saved_word_hit, // 已保存描述符命中准备阶段的数据字。
  input wire logic [p_prepared_tile_width-1:0] i_committing_tile, // 待接收分块的完整准备数据。
  input wire logic [1:0][16:0] i_coordinate_low_difference, // 坐标低位减去填充值的结果和借位。
  input wire logic [1:0][p_coord_width-1:0] i_coordinate_payload, // 当前操作需要保存的输入列、行坐标。
  input wire logic [1:0][32:0] i_coordinate_product_sum, // 坐标乘积相加后的列、行结果。
  input wire logic [4:0] i_current_q_div3, // 当前归约位置除以三的商。
  input wire logic [15:0] i_current_q_remainder, // 当前归约位置除以三的余数。
  input wire logic [2:0] i_decode_end_o_equal, // 三种除法解码对应的行末比较结果。
  input wire logic i_descriptor_padding, // 已保存描述符的填充判断。
  input wire logic [p_read_width-1:0] i_descriptor_word_data, // 描述符准备阶段保存的数据字。
  input wire logic i_finishing_tile, // 当前周期完成分块输出。
  input wire logic [31:0] i_group_address_sum, // 通道乘积加输入起始地址的结果。
  input wire logic i_group_end_o_equal, // 当前传输到达通道组末尾。
  input wire logic [5:0][15:0] i_group_range_channel, // 各运行位置对应的组内通道索引。
  input wire logic i_group_shape_o_valid, // 每组通道数可按位移计算商和余数。
  input wire logic [4:0] i_group_width_shift, // 每组通道数对应的二进制位移量。
  input wire logic i_history_limit_carry, // 历史位置上界低位运算产生进位。
  input wire logic [5:0] i_k_decode_value, // 三列卷积核的行列解码结果。
  input wire logic [15:0] i_kernel_column_payload, // 当前操作需要保存的卷积核列。
  input wire logic [15:0] i_kernel_decode_column, // 按配置掩码得到的卷积核列。
  input wire logic i_kernel_shape_o_valid, // 卷积核宽度可按位移计算商和余数。
  input wire logic [4:0] i_kernel_width_shift, // 卷积核宽度对应的二进制位移量。
  input wire logic [32:0] i_next_q_current, // 当前传输之后的归约位置。
  input wire logic [31:0] i_next_row_addr, // 下一输出行起点的字节地址。
  input wire logic [p_count_width-1:0] i_next_row_idx, // 下一输出行索引。
  input wire logic i_next_row_last, // 下一输出行为分块最后一行。
  input wire logic i_next_row_padding, // 下一输出行起点使用填充值。
  input wire logic [31:0] i_next_row_pixel, // 下一输出行起点的线性像素索引。
  input wire logic i_next_tap_padding, // 下一卷积核位置使用填充值。
  input wire logic [1:0] i_p_cache_select, // 需要保存的输出位置历史项。
  input wire logic i_p_fast_valid, // 历史位置快速解码结果有效。
  input wire logic [31:0] i_pixel_payload, // 当前操作需要保存的线性像素索引。
  input wire logic [p_row_high_width-1:0] i_position_high_minus_one, // 计算得到的输出位置上限高位减一值。
  input wire logic i_pred_busy, // 后续使用预测器正在工作。
  input wire logic i_pred_done, // 后续使用预测已经完成。
  input wire logic [31:0] i_pred_rank, // 预测得到的后续使用次序。
  input wire logic i_pred_start, // 当前周期启动后续使用预测。
  input wire logic signed [32:0] i_row_pair_dx_sum, // 需要保存的相邻输出位置对列位移。
  input wire logic i_row_wrap, // 输出位置沿列推进时换行。
  input wire logic [1:0][47:0] i_shared_channel_product, // 共享乘法器返回的两项通道乘积。
  input wire logic [3:0][31:0] i_shared_coordinate_product, // 共享乘法器返回的四项坐标乘积。
  input wire logic i_stream_operation_accept, // 当前运行输出被接收。
  input wire logic i_stream_response_error, // 当前缓存响应返回错误。
  input wire logic i_tap_wrap, // 卷积核位置沿列推进时换行。
  input wire logic i_tile_commit, // 当前周期接收分块描述符。
  input wire logic i_wr_ready, // 当前输出数据可被接收。
  input wire logic i_wr_valid, // 当前输出数据有效。
  output logic [2:0][31:0] o_descriptor_index, // 分块起始输出位置、归约位置和卷积核位置。
  output logic [1:0][32:0] o_group_advance, // 连续分组和跨行分组的下一个位置。
  output logic [4:0][p_count_width-1:0] o_output_count, // 当前行列索引、分块行列数和有效列数。
  output logic [1:0][15:0] o_output_coordinate, // 当前输出位置的列、行坐标。
  output logic [3:0][15:0] o_kernel_coordinate, // 当前和初始卷积核位置的行、列坐标。
  output logic [1:0][31:0] o_group_base, // 当前卷积核位置和输出行的通道组地址。
  output logic [1:0][p_coord_width-1:0] o_input_coordinate, // 当前输入位置的列、行坐标。
  output logic [1:0][15:0] o_history_coordinate, // 历史输出位置的列、行坐标。
  output logic [1:0][32:0] o_wrap_dx, // 输出行和卷积核换行的有符号列位移。
  output logic [1:0][32:0] o_axis_pixels, // 输出行和卷积核换行的像素跨度。
  output logic [1:0][32:0] o_wrap_pixels, // 输出行和卷积核换行的有符号像素位移。
  output logic [1:0][31:0] o_step_bytes, // 输出位置和卷积核位置沿列推进的字节数。
  output logic [1:0][31:0] o_wrap_bytes, // 输出行和卷积核换行的字节位移。
  output logic [1:0][p_coord_width-1:0] o_row_coordinate, // 当前输出行起点的输入列、行坐标。
  output logic [2:0] o_coordinate_valid, // 行地址、当前坐标地址和行坐标的有效位。
  output logic [2:0][31:0] o_decode, // 除法解码的被除位置、商和余数。
  output logic [1:0][31:0] o_address_product, // 地址生成保存的像素乘积和通道乘积。
  output logic [1:0] o_address_step_phase, // 地址步长准备阶段。
  output conv_im2col_pkg::conv_cfg_t o_configuration, // 已保存的卷积配置。
  output logic [15:0] o_initial_channel, // 分块的初始通道索引。
  output logic o_configured, // 配置已经通过检查。
  output logic [1:0] o_coordinate_borrow, // 坐标减去填充值时的列、行借位。
  output logic [3:0][31:0] o_coordinate_product, // 坐标生成阶段保存的四个乘积。
  output logic [1:0][32:0] o_coordinate_sum, // 坐标生成阶段保存的列、行加法结果。
  output logic o_fragment_image_fits, // 输入片段能够保存在窗口缓存。
  output logic o_geometry_tile, // 当前分块使用几何预测。
  output logic [31:0] o_group_base_addr, // 输入像素对应的通道组起始地址。
  output logic [31:0] o_group_count, // 已保存的调度通道组数。
  output logic [31:0] o_history_position, // 最近一次解码的输出位置。
  output logic o_history_overflow, // 最近输出位置的上界计算产生进位。
  output logic o_history_position_valid, // 最近输出位置历史项有效。
  output logic [31:0] o_line_hint_rank, // 最近一次预测得到的后续使用次序。
  output logic o_line_hint_valid, // 最近一次预测返回的提示有效。
  output logic o_narrow_output, // 当前分块使用窄通道输出。
  output logic [3:0] o_history_valid, // 四个输出位置历史项的有效位。
  output logic o_padding, // 当前输出位置使用填充值。
  output logic o_past_active, // 当前列已经越过有效输出范围。
  output logic [31:0] o_pixel_index, // 当前输入像素的线性索引。
  output logic [31:0] o_position_count, // 配置中的输出位置总数。
  output logic [p_row_high_width-1:0] o_position_high_minus_one, // 输出位置上限高位减一结果。
  output logic [32:0] o_reduction_index, // 当前归约位置及最高进位。
  output logic [31:0] o_reduction_len, // 配置中的归约长度。
  output logic [31:0] o_row_base_addr, // 当前输出行起点的字节地址。
  output logic [31:0] o_row_base_pixel, // 当前输出行起点的线性像素索引。
  output logic o_row_last, // 当前输出行为分块最后一行。
  output logic signed [32:0] o_row_pair_dx, // 相邻输出位置对的有符号列位移。
  output logic [p_slot_width-1:0] o_slot, // 当前分块的目标存储槽。
  output logic [31:0] o_tensor_bytes, // 输入张量的字节数。
  output logic o_tile_done, // 分块输出完成脉冲。
  output logic [31:0] o_word_addr, // 已保存缓存字的字节地址。
  output logic [p_read_width-1:0] o_word_data, // 已保存的缓存字。
  output logic o_word_valid // 已保存缓存字有效。
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w = p_count_width;
  localparam int p_prepared_slot_w = p_slot_width;
  localparam int p_prepared_coord_w = p_coord_width;
  `include "conv_im2col_prepared_tile.svh"
  prepared_tile_t prepared_tile;
  assign prepared_tile = i_committing_tile;

  logic [2:0] decode_equal;
  // 解码索引和三个完整目标共享分组比较结构，各运行过程直接使用完成资格。
  for (genvar target_index = 0; target_index < 3; target_index++) begin : g_decode_match
    conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_match (
      .i_a(o_decode[0]), .i_b(o_descriptor_index[target_index]), .o_equal(decode_equal[target_index])
    );
  end
  logic [1:0][32:0] configuration_wrap_difference;
  // 配置阶段的完整回绕减法按低段借位和高段候选并行计算。
  conv_runtime_wrap_difference u_row_wrap_difference (
    .i_step(o_configuration.stride_w), .i_span(o_wrap_dx[0]),
    .o_difference(configuration_wrap_difference[0])
  );
  conv_runtime_wrap_difference u_tap_wrap_difference (
    .i_step(o_configuration.dilation_w), .i_span(o_wrap_dx[1]),
    .o_difference(configuration_wrap_difference[1])
  );

  // 六个坐标字段按输出列、输出行、当前核行、当前核列、初始核行和初始核列排列。
  logic [5:0] descriptor_coordinate_write, stream_coordinate_write, state_coordinate_write;
  logic [5:0][15:0] descriptor_coordinate_data, stream_coordinate_data, state_coordinate_data;
  logic [5:0] coordinate_write;
  logic [5:0][15:0] coordinate_data;
  logic tile_control_known, stream_control_known;

  // 候选值与字段资格独立于晚到的提交、输出接收信号，末级只选择完整候选。
  always_comb begin
    descriptor_coordinate_write = '0;
    descriptor_coordinate_data = '0;
    descriptor_coordinate_data[0] = prepared_tile.output_x;
    descriptor_coordinate_data[1] = prepared_tile.output_y;
    descriptor_coordinate_data[2] = 16'(prepared_tile.kernel_y);
    descriptor_coordinate_data[3] = i_kernel_column_payload;
    descriptor_coordinate_data[4] = 16'(prepared_tile.kernel_y);
    descriptor_coordinate_data[5] = 16'(prepared_tile.kernel_x);
    if (prepared_tile.invalid) begin
    end else if (prepared_tile.fast) begin
      descriptor_coordinate_write[5:2] = '1;
      if (prepared_tile.output_position_update) descriptor_coordinate_write[1:0] = '1;
    end

    stream_coordinate_write = '0;
    stream_coordinate_data = '0;
    if (i_chunk_reaches_end) begin
      if (o_row_last) begin
      end else begin
        stream_coordinate_write[3:2] = '1;
        stream_coordinate_data[2] = 16'(32'(o_kernel_coordinate[2]));
        stream_coordinate_data[3] = i_kernel_column_payload;
        stream_coordinate_write[0] = 1'b1;
        if (i_row_wrap) begin
          stream_coordinate_write[1] = 1'b1;
          stream_coordinate_data[0] = 16'd0;
          stream_coordinate_data[1] = 16'(32'(o_output_coordinate[1]) + 1);
        end else stream_coordinate_data[0] = 16'(32'(o_output_coordinate[0]) + 1);
      end
    end else begin
      if (o_past_active || !i_active_after_chunk) begin
      end else if (i_group_end_o_equal) begin
        stream_coordinate_write[3] = 1'b1;
        stream_coordinate_data[3] = i_kernel_column_payload;
        if (i_tap_wrap) begin
          stream_coordinate_write[2] = 1'b1;
          stream_coordinate_data[2] = 16'(32'(o_kernel_coordinate[0]) + 1);
        end
      end
    end
  end

  // 四态控制保持顺序 case 的匹配规则；二态综合时两项完整性资格均为常量一。
  always_comb begin
    tile_control_known = 1'b0;
    stream_control_known = 1'b0;
    case (i_tile_commit)
      1'b0, 1'b1: tile_control_known = 1'b1;
      default: ;
    endcase
    case (i_stream_operation_accept)
      1'b0, 1'b1: stream_control_known = 1'b1;
      default: ;
    endcase
    // 状态候选保持原有先后顺序，空操作状态同样阻止后续状态写入坐标。
    state_coordinate_write = '0;
    state_coordinate_data = '0;
    case (1'b1)
      (i_state[$clog2(DESCRIPTOR_CHECK)] && tile_control_known && stream_control_known): ;
      (tile_control_known && (i_state[$clog2(WAIT_WORD)] ||
                             i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)])): ;
      i_state[$clog2(P_HISTORY)]: ;
      i_state[$clog2(P_DECODE)]: if (i_p_fast_valid) begin
        state_coordinate_write[1:0] = '1;
        state_coordinate_data[0] = 16'(i_fast_coordinate[0]);
        state_coordinate_data[1] = 16'(i_fast_coordinate[1]);
      end
      i_state[$clog2(P_START)]: ;
      i_state[$clog2(P_WAIT)]: if (decode_equal[0]) begin
        state_coordinate_write[1:0] = '1;
        state_coordinate_data[0] = 16'(o_decode[2]);
        state_coordinate_data[1] = 16'(o_decode[1]);
      end
      i_state[$clog2(Q_DECODE)]: ;
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: ;
      i_state[$clog2(K_DECODE)]: begin
        if (i_kernel_shape_o_valid) begin
          state_coordinate_write[5:2] = '1;
          state_coordinate_data[2] = 16'(o_descriptor_index[2] >> i_kernel_width_shift);
          state_coordinate_data[3] = i_kernel_column_payload;
          state_coordinate_data[4] = 16'(o_descriptor_index[2] >> i_kernel_width_shift);
          state_coordinate_data[5] = i_kernel_decode_column;
        end else if (o_configuration.kernel_w == 3 && o_descriptor_index[2] < 9) begin
          state_coordinate_write[5:2] = '1;
          state_coordinate_data[2] = 16'(i_k_decode_value[5:2]);
          state_coordinate_data[3] = i_kernel_column_payload;
          state_coordinate_data[4] = 16'(i_k_decode_value[5:2]);
          state_coordinate_data[5] = 16'(i_k_decode_value[1:0]);
        end
      end
      i_state[$clog2(K_START)]: ;
      i_state[$clog2(K_WAIT)]: if (decode_equal[2]) begin
        state_coordinate_write[5:2] = '1;
        state_coordinate_data[2] = 16'(o_decode[1]);
        state_coordinate_data[3] = i_kernel_column_payload;
        state_coordinate_data[4] = 16'(o_decode[1]);
        state_coordinate_data[5] = 16'(o_decode[2]);
      end
      default: ;
    endcase
  end

  conv_runtime_coordinate_select u_coordinate_select (
    .i_cfg_write(i_cfg_valid && i_cfg_ready),
    .i_tile_commit(i_tile_commit),
    .i_stream_error(i_stream_response_error),
    .i_stream_accept(i_stream_operation_accept),
    .i_descriptor_write(descriptor_coordinate_write),
    .i_descriptor_data(descriptor_coordinate_data),
    .i_stream_write(stream_coordinate_write),
    .i_stream_data(stream_coordinate_data),
    .i_state_write(state_coordinate_write),
    .i_state_data(state_coordinate_data),
    .o_write(coordinate_write),
    .o_data(coordinate_data)
  );

  // 使用既有寄存边沿保存各坐标，停顿及空操作保留原值。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      o_output_coordinate <= '0;
      o_kernel_coordinate <= '0;
    end else begin
      for (int field_index = 0; field_index < 2; field_index++) begin
        if (coordinate_write[field_index]) o_output_coordinate[field_index] <= coordinate_data[field_index];
      end
      for (int field_index = 0; field_index < 4; field_index++) begin
        if (coordinate_write[field_index+2]) o_kernel_coordinate[field_index] <= coordinate_data[field_index+2];
      end
    end
  end

  // 保存前端配置、描述符和坐标状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      o_configuration <= '0;
      o_configured <= 0;
      o_tile_done <= 0;
      o_fragment_image_fits <= 0;
      o_reduction_len <= 0;
      o_position_count <= 0;
      o_tensor_bytes <= 0;
      o_position_high_minus_one <= '1;
      o_group_advance[0] <= 33'd0;
      o_group_advance[1] <= 33'd0;
      o_descriptor_index[0] <= 0;
      o_descriptor_index[1] <= 0;
      o_descriptor_index[2] <= 0;
      o_output_count[0] <= 0;
      o_output_count[1] <= 0;
      o_output_count[2] <= 0;
      o_output_count[3] <= p_count_width'(p_size);
      o_output_count[4] <= 0;
      o_row_last <= 1'b0;
      o_past_active <= 1'b1;
      o_narrow_output <= 1'b0;
      o_initial_channel <= 16'(0);
      o_group_base[0] <= 0;
      o_group_base[1] <= 0;
      o_reduction_index <= 0;
      o_input_coordinate[0] <= p_coord_width'(0);
      o_input_coordinate[1] <= p_coord_width'(0);
      o_pixel_index <= 32'(0);
      o_padding <= 0;
      o_word_data <= 0;
      o_word_addr <= 0;
      o_word_valid <= 0;
      o_slot <= 0;
      o_group_count <= 0;
      o_geometry_tile <= 0;
      o_line_hint_valid <= 0;
      o_line_hint_rank <= 32'hffff_ffff;
      o_history_valid <= 0;
      o_history_position_valid <= 0;
      o_history_position <= 0;
      o_history_overflow <= 0;
      o_history_coordinate[1] <= 0;
      o_history_coordinate[0] <= 0;
      o_address_step_phase <= 0;
      o_wrap_dx[0] <= 33'(0);
      o_wrap_dx[1] <= 33'(0);
      o_row_pair_dx <= 0;
      o_axis_pixels[0] <= 33'(0);
      o_axis_pixels[1] <= 33'(0);
      o_wrap_pixels[0] <= 33'(0);
      o_wrap_pixels[1] <= 33'(0);
      o_step_bytes[0] <= 0;
      o_step_bytes[1] <= 0;
      o_wrap_bytes[0] <= 0;
      o_wrap_bytes[1] <= 0;
      o_coordinate_valid[0] <= 0;
      o_coordinate_valid[1] <= 0;
      o_coordinate_valid[2] <= 0;
      o_row_coordinate[0] <= p_coord_width'(0);
      o_row_coordinate[1] <= p_coord_width'(0);
      o_row_base_pixel <= 32'(0);
      o_row_base_addr <= 0;
    end else begin
      o_tile_done <= i_finishing_tile;
      // 检查周期保存数据字与填充状态，同周期输出推进可以继续更新下一运行位置。
      if (i_descriptor_check) begin
        o_padding <= i_descriptor_padding;
        if (i_committing_saved_word_hit) begin
          o_word_data <= i_descriptor_word_data;
          o_word_addr <= {i_addr[31:p_word_shift], {p_word_shift{1'b0}}};
          o_word_valid <= 1'b1;
        end
      end
      if (i_state[$clog2(WAIT_WORD)] && i_wr_valid && i_wr_ready) begin
        o_word_data <= i_cache_rsp_data;
        o_word_addr <= {i_addr[31:p_word_shift],{p_word_shift{1'b0}}};
        o_word_valid <= 1;
      end
      if (o_address_step_phase==2) begin
        o_row_pair_dx <= i_row_pair_dx_sum;
        o_wrap_pixels[0] <= i_wrap_pixel_sum[0];
        o_wrap_pixels[1] <= i_wrap_pixel_sum[1];
        o_address_step_phase <= 1;
      end else if (o_address_step_phase==1) begin
        o_address_step_phase <= 3;
      end else if (o_address_step_phase==3) begin
        o_wrap_bytes[0] <= i_shared_channel_product[0][31:0] << o_configuration.input_s16;
        o_wrap_bytes[1] <= i_shared_channel_product[1][31:0] << o_configuration.input_s16;
        o_address_step_phase <= 0;
      end
      if (i_cfg_prepare_phase == 3'd1) begin
        o_axis_pixels[0] <= {1'b0, i_shared_coordinate_product[3]};
        // 配置已由前一边沿保存，分块接收前完成初始通道组位置计算。
        o_group_advance <= i_initial_group;
      end
      if (i_cfg_prepare_phase == 3'd2) begin
        // 先保存无符号乘积，下一阶段计算有符号回绕位移。
        o_wrap_dx[0] <= {1'b0, i_shared_coordinate_product[0]};
        o_wrap_dx[1] <= {1'b0, i_shared_coordinate_product[1]};
        o_axis_pixels[1] <= {1'b0, i_shared_coordinate_product[2]};
        o_step_bytes[0] <= i_shared_coordinate_product[3] << o_configuration.input_s16;
      end
      if (i_cfg_prepare_phase==3) begin
        o_wrap_dx[0] <= configuration_wrap_difference[0];
        o_wrap_dx[1] <= configuration_wrap_difference[1];
        o_step_bytes[1] <= i_shared_coordinate_product[3] << o_configuration.input_s16;
        o_address_step_phase <= 2'd2;
      end
      if (i_cfg_prepare_phase==4) begin
        o_configured <= i_cfg_ok;
        o_reduction_len <= 32'(i_cfg_red);
        o_position_count <= i_cfg_positions;
        o_tensor_bytes <= 32'(i_cfg_input_bytes);
        // 配置边沿同时保存位置上限及其高位减一值，供低位进位时比较。
        o_position_high_minus_one <= i_position_high_minus_one;
        o_fragment_image_fits <= p_cache_ways>=2 &&
          i_cfg_input_bytes <= ((64'(o_configuration.input_c)<<o_configuration.input_s16)<<$clog2(p_cache_sets));
      end
      if (i_pred_done) begin o_line_hint_valid <= 1;
      o_line_hint_rank <= i_pred_rank;end
      if (i_pred_start) o_line_hint_valid <= 0;
      // 配置、描述符提交与各运行状态互斥选择，公共写条件只参与末级组合。
      unique case (1'b1)
        (i_cfg_valid && i_cfg_ready): begin
       o_configuration <= i_cfg;
       o_configured <= 0;
        o_word_valid <= 0;
        o_reduction_len <= 0;
        o_fragment_image_fits <= 0;
        o_position_count <= 0;
        o_tensor_bytes <= 0;
        o_position_high_minus_one <= '1;
        o_group_count <= i_cfg_sched_groups;
        o_geometry_tile <= 0;
        o_line_hint_valid <= 0;
        o_history_valid <= 0;
        o_history_position_valid <= 0;
        o_address_step_phase <= 2'd0;
        o_coordinate_valid[0] <= 0;
        o_coordinate_valid[1] <= 0;
        o_coordinate_valid[2] <= 0;
        end
        i_tile_commit: begin
        if (prepared_tile.invalid) begin
        end else begin
          o_descriptor_index[0] <= prepared_tile.position;
          o_descriptor_index[1] <= prepared_tile.reduction;
          o_reduction_index <= {1'b0,prepared_tile.reduction};
          o_group_advance[0] <= prepared_tile.next_group;
          o_group_advance[1] <= prepared_tile.skip_group;
          o_row_last <= prepared_tile.rows == p_count_width'(1);
          o_output_count[2] <= prepared_tile.rows;
          o_output_count[3] <= prepared_tile.columns;
          o_output_count[4] <= prepared_tile.active_columns;
          o_past_active <= 1'b0;
          o_output_count[0] <= 0;
          o_output_count[1] <= 0;
          o_slot <= prepared_tile.slot;
          o_narrow_output <= prepared_tile.narrow_output;
          o_coordinate_valid[0] <= 0;
          o_coordinate_valid[1] <= 0;
          o_coordinate_valid[2] <= 0;
          o_geometry_tile <= prepared_tile.geometry;
          if (prepared_tile.fast) begin
            o_descriptor_index[2] <= prepared_tile.tap;
            o_initial_channel <= 16'(prepared_tile.channel);
            o_input_coordinate[0] <= i_coordinate_payload[0];
            o_input_coordinate[1] <= i_coordinate_payload[1];
            o_pixel_index <= i_pixel_payload;
            if (!p_register_descriptor) o_padding <= prepared_tile.padding;
            o_group_base[0] <= i_group_payload[0];
            o_group_base[1] <= i_group_payload[1];
            o_coordinate_valid[0] <= 1;
            o_coordinate_valid[1] <= 1;
            o_coordinate_valid[2] <= 1;
            o_row_coordinate[0] <= prepared_tile.input_x;
            o_row_coordinate[1] <= prepared_tile.input_y;
            o_row_base_pixel <= prepared_tile.pixel;
            o_row_base_addr <= prepared_tile.address;
          end
        end
        end
        i_stream_response_error: begin
        end
        i_stream_operation_accept: begin
          // 行推进和内核推进分别确定字段写入资格。
          if (i_stream_update[0] || i_stream_update[2]) begin
            o_input_coordinate[0] <= i_coordinate_payload[0];
            o_input_coordinate[1] <= i_coordinate_payload[1];
          end
          if (i_stream_update[1] || i_stream_update[3]) begin
            o_pixel_index <= i_pixel_payload;
            o_group_base[0] <= i_group_payload[0];
          end
          if (i_stream_update[1]) begin
            o_padding <= i_next_row_padding;
            o_group_base[1] <= i_group_payload[1];
          end else if (i_stream_update[3]) o_padding <= i_next_tap_padding;
          if (i_chunk_reaches_end) begin
            if (o_row_last) begin o_tile_done <= 1; end
            else begin
              o_output_count[0] <= i_next_row_idx;
              o_row_last <= i_next_row_last;
              o_output_count[1] <= 0;
              o_reduction_index <= {1'b0,o_descriptor_index[1]};
               o_past_active <= 1'b0;
              if (o_coordinate_valid[0] && !o_geometry_tile) begin
                 o_coordinate_valid[1] <= 1;
                o_row_coordinate[0] <= p_coord_width'(i_next_row_coordinate[0]);
                o_row_coordinate[1] <= p_coord_width'(i_next_row_coordinate[1]);
                o_row_base_pixel <= 32'(i_next_row_pixel);
                o_row_base_addr <= i_next_row_addr;
              end else if (o_coordinate_valid[2]) begin
                o_row_coordinate[0] <= i_next_row_coordinate[0];
                o_row_coordinate[1] <= i_next_row_coordinate[1];
                o_coordinate_valid[0] <= 0;
                o_coordinate_valid[1] <= 0;
              end else begin o_coordinate_valid[0] <= 0;end
            end
          end else begin
            o_output_count[1] <= o_output_count[1]+p_count_width'(i_chunk_count);
            o_reduction_index <= i_next_q_current;
            // 填充列同样推进计数，保留原有定宽减法的回绕结果。
             // 仅在写入握手时推进；到达有效尾部后保持，直到下一行或描述符。
             o_past_active <= o_past_active || !i_active_after_chunk;
             if (o_past_active || !i_active_after_chunk) begin
             end
            else if (i_group_end_o_equal) begin
              if (o_coordinate_valid[1]) begin
              end else o_coordinate_valid[1] <= 0;
            end
          end
        end
        (i_state[$clog2(DESCRIPTOR_CHECK)] && !i_tile_commit && !i_stream_operation_accept): ;
        (!i_tile_commit && i_stream_response_error !== 1'b1 && i_stream_operation_accept !== 1'b1 &&
          (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)])): ;
        i_state[$clog2(P_HISTORY)]: ;
        i_state[$clog2(P_DECODE)]: if (i_p_fast_valid) begin
          o_history_position_valid <= 1;
          o_history_position <= o_descriptor_index[0];
          o_history_overflow <= (&o_descriptor_index[0][31:16]) && i_history_limit_carry;
          o_history_coordinate[1] <= 16'(i_fast_coordinate[1]);
          o_history_coordinate[0] <= 16'(i_fast_coordinate[0]);
          o_history_valid[i_p_cache_select] <= 1;
        end
        i_state[$clog2(P_START)]: ;
        i_state[$clog2(P_WAIT)]: if (decode_equal[0]) begin
          o_history_position_valid <= 1;
          o_history_position <= o_descriptor_index[0];
          o_history_overflow <= (&o_descriptor_index[0][31:16]) && i_history_limit_carry;
          o_history_coordinate[1] <= 16'(o_decode[1]);
          o_history_coordinate[0] <= 16'(o_decode[2]);
          o_history_valid[i_p_cache_select] <= 1;
        end
        i_state[$clog2(Q_DECODE)]: begin
          if (o_descriptor_index[1]==0) begin
            o_descriptor_index[2] <= 0;
            o_initial_channel <= 16'(0);
          end
          else if (i_group_shape_o_valid) begin
            o_descriptor_index[2] <= o_descriptor_index[1] >> i_group_width_shift;
            // 通道余数与分组范围准备共用已经保存的配置掩码。
            o_initial_channel <= i_group_range_channel[2];
          end else if (o_configuration.group_c==3 && o_descriptor_index[1]<27) begin
            o_descriptor_index[2] <= 32'(i_current_q_div3);
            o_initial_channel <= i_current_q_remainder;
          end
        end
        i_state[$clog2(Q_START)]: ;
        i_state[$clog2(Q_WAIT)]: if (decode_equal[1]) begin
          o_descriptor_index[2] <= o_decode[1];
          o_initial_channel <= 16'(o_decode[2]);
        end
        i_state[$clog2(K_DECODE)]: ;
        i_state[$clog2(K_START)]: ;
        i_state[$clog2(K_WAIT)]: ;
        i_state[$clog2(COORD)]: begin
          o_coordinate_valid[1] <= 0;
        end
        i_state[$clog2(COORD_SUM)]: ;
        i_state[$clog2(COORD_BORROW)]: ;
        i_state[$clog2(COORD_PAD)]: begin
          o_input_coordinate[0] <= i_coordinate_payload[0];
          o_input_coordinate[1] <= i_coordinate_payload[1];
        end
        i_state[$clog2(ADDRESS)]: begin
          if (o_output_count[1]==0) begin
            o_coordinate_valid[2] <= 1;
            o_row_coordinate[0] <= o_input_coordinate[0];
            o_row_coordinate[1] <= o_input_coordinate[1];
          end
          if (!i_address_position_valid) begin
            o_padding <= 1;
          end else if (!o_geometry_tile || o_output_count[1]!=0 || (!i_pred_busy && !i_cache_hint_pending)) begin
            o_padding <= 0;
          end
        end
        i_state[$clog2(ADDRESS_PIXEL)]: begin
          o_pixel_index <= i_pixel_payload;
        end
        i_state[$clog2(ADDRESS_PRODUCT)]: ;
        i_state[$clog2(ADDRESS_MERGE)]: ;
        i_state[$clog2(ADDRESS_BASE)]: ;
        i_state[$clog2(ADDRESS_CHANNEL)]: begin
          o_group_base[0] <= i_group_payload[0];
          o_coordinate_valid[1] <= 1;
          if (o_output_count[1]==0) begin
            o_coordinate_valid[0] <= 1;
            o_row_coordinate[0] <= o_input_coordinate[0];
            o_row_coordinate[1] <= o_input_coordinate[1];
            o_row_base_pixel <= o_pixel_index;
            o_row_base_addr <= i_channel_addr;
            o_group_base[1] <= i_group_payload[1];
          end
        end
        i_state[$clog2(ADDRESS_MATCH)]: begin
          o_padding <= !i_address_position_valid;
        end
        i_state[$clog2(FETCH)]: ;
        (i_state[$clog2(IDLE)] && !(i_cfg_valid && i_cfg_ready) && !i_tile_commit): ;
        default: begin o_configured <= 0;  end
      endcase
    end
  end
  // 解码计数与坐标运算由运行状态保护，复位期间保持数据寄存器。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else begin
      unique case (1'b1)
        (i_cfg_valid && i_cfg_ready): ;
        i_tile_commit: ;
        (!i_tile_commit && (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] ||
                          i_state[$clog2(ZERO_STREAM)])): ;
        i_state[$clog2(P_DECODE)]: ;
        i_state[$clog2(P_START)]: begin
          o_decode[0] <= 0;
          o_decode[1] <= 0;
          o_decode[2] <= 0;
        end
        i_state[$clog2(P_WAIT)]: begin
          if (decode_equal[0]) begin
          end else begin
            o_decode[0] <= i_decode_advance[0];
            if (i_decode_end_o_equal[0]) begin
              o_decode[2] <= 0;
              o_decode[1] <= o_decode[1] + 1;
            end else o_decode[2] <= i_decode_advance[1];
          end
        end
        i_state[$clog2(Q_DECODE)]: ;
        i_state[$clog2(Q_START)]: begin
          o_decode[0] <= 0;
          o_decode[1] <= 0;
          o_decode[2] <= 0;
        end
        i_state[$clog2(Q_WAIT)]: begin
          if (decode_equal[1]) begin
          end else begin
            o_decode[0] <= i_decode_advance[0];
            if (i_decode_end_o_equal[1]) begin
              o_decode[2] <= 0;
              o_decode[1] <= o_decode[1] + 1;
            end else o_decode[2] <= i_decode_advance[1];
          end
        end
        i_state[$clog2(K_DECODE)]: ;
        i_state[$clog2(K_START)]: begin
          o_decode[0] <= 0;
          o_decode[1] <= 0;
          o_decode[2] <= 0;
        end
        i_state[$clog2(K_WAIT)]: begin
          if (decode_equal[2]) begin
          end else begin
            o_decode[0] <= i_decode_advance[0];
            if (i_decode_end_o_equal[2]) begin
              o_decode[2] <= 0;
              o_decode[1] <= o_decode[1] + 1;
            end else o_decode[2] <= i_decode_advance[1];
          end
        end
        i_state[$clog2(COORD)]: begin
          o_coordinate_product <= i_shared_coordinate_product;
        end
        i_state[$clog2(COORD_SUM)]: begin
          o_coordinate_sum <= i_coordinate_product_sum;
        end
        i_state[$clog2(COORD_BORROW)]: begin
          for (int axis = 0; axis < 2; axis++) begin
            o_coordinate_sum[axis][15:0] <= i_coordinate_low_difference[axis][15:0];
            o_coordinate_borrow[axis] <= i_coordinate_low_difference[axis][16];
          end
        end
        i_state[$clog2(COORD_PAD)]: ;
        i_state[$clog2(ADDRESS)]: begin
          if (!i_address_position_valid) begin
          end else if (!o_geometry_tile || o_output_count[1] != 0 || (!i_pred_busy && !i_cache_hint_pending)) begin
            o_address_product[0] <= i_shared_coordinate_product[0];
          end
        end
        i_state[$clog2(ADDRESS_PIXEL)]: ;
        i_state[$clog2(ADDRESS_MERGE)]: o_address_product[1] <= i_shared_channel_product[0][31:0];
        i_state[$clog2(ADDRESS_BASE)]: o_group_base_addr <= i_group_address_sum;
        i_state[$clog2(ADDRESS_CHANNEL)]: ;
        i_state[$clog2(FETCH)]: ;
        default: ;
      endcase
    end
  end
endmodule
`default_nettype wire
