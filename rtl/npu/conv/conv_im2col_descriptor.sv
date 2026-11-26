// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 输入描述符准备、窗口复用及提交数据保存。
module conv_im2col_descriptor #(
  parameter int p_size=16,
  parameter int p_slot_w=3,
  parameter int p_lanes=2,
  parameter int p_line_bytes=16,
  parameter int p_cache_policy=3,
  parameter bit p_register_descriptor=1'b1,
  parameter int p_rw=$clog2(p_size+1),
  localparam int p_lane_bytes=p_lanes <= 4 ? 4 : (1 << $clog2(p_lanes)),
  localparam int p_cache_read_bytes=p_lane_bytes < p_line_bytes ? p_lane_bytes : p_line_bytes,
  localparam int p_cache_read_width=8 * p_cache_read_bytes,
  localparam int p_word_shift=$clog2(p_cache_read_bytes),
  localparam int p_row_low_w=p_rw < 32 ? p_rw : 31,
  localparam int p_row_high_w=32 - p_row_low_w,
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_saved_group_lanes=p_lanes <= 16 ? p_lane_bytes : 4,
  localparam int p_coord_w=35,
  localparam int p_prepared_tile_width=458+2*p_coord_w+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input wire logic i_clk, // 描述符处理时钟
  input wire logic i_rst_n, // 异步低有效复位
  input wire logic i_cfg_valid, // 新配置有效
  input wire logic i_cfg_ready, // 当前允许接收新配置
  input wire logic i_tile_valid, // 输入描述符有效
  input wire logic i_tile_ready, // 当前允许接收描述符
  input wire logic i_tile_finish, // 当前分块在本周期完成
  input wire logic [31:0] i_tile_p0, // 输入描述符的空间起点
  input wire logic [31:0] i_tile_q0, // 输入描述符的归约起点
  input wire logic [p_rw-1:0] i_tile_rows, // 输入描述符的有效行数
  input wire logic [p_rw-1:0] i_tile_cols, // 输入描述符的列数，零表示完整分块
  input wire logic [p_slot_w-1:0] i_tile_slot, // 输入描述符的目标缓存槽
  input wire logic [31:0] i_tile_group, // 输入描述符的通道组序号
  input wire logic i_tile_narrow, // 输入描述符采用窄输出格式
  input wire logic i_error, // 当前任务出现错误
  input wire conv_im2col_frontend_pkg::st_t i_state, // 前端当前运行状态
  input wire conv_im2col_pkg::conv_cfg_t i_c, // 当前卷积配置
  input wire logic [31:0] i_reduction_len, // 当前配置的归约长度
  input wire logic [31:0] i_position_count, // 当前配置的空间位置数量
  input wire logic [p_row_high_w-1:0] i_position_high_minus_one_q, // 空间位置数量高段减一的保存值
  input wire logic [15:0] i_last_group_channel_q, // 通道组末位置的保存值
  input wire logic i_group_nonzero_q, // 保存的通道组非零标志
  input wire logic [16:0] i_initial_group_remaining, // 当前描述符起点的剩余通道数
  input wire logic [5:0][p_saved_group_lanes:0] i_group_range_next, // 各候选通道位置的组内范围标志
  input wire logic [31:0] i_p0, // 当前描述符的空间起点
  input wire logic [31:0] i_q0, // 当前描述符的归约起点
  input wire logic [31:0] i_tap0, // 当前描述符的卷积核位置
  input wire logic [32:0] i_next_group_q, // 下一通道组的归约位置
  input wire logic [32:0] i_skip_group_q, // 跳过一个通道组的归约位置
  input wire logic [p_tile_count_w-1:0] i_rows_q, // 当前描述符保存的有效行数
  input wire logic [p_tile_count_w-1:0] i_cols_q, // 当前描述符保存的列数
  input wire logic [15:0] i_ox_q, // 当前输出列坐标
  input wire logic [15:0] i_oy_q, // 当前输出行坐标
  input wire logic [15:0] i_ky0_q, // 当前描述符的卷积核行
  input wire logic [15:0] i_kx0_q, // 当前描述符的卷积核列
  input wire logic [15:0] i_ch0_q, // 当前描述符的组内起始通道
  input wire logic [31:0] i_ky0, // 扩展后的当前卷积核行
  input wire logic [31:0] i_kx0, // 扩展后的当前卷积核列
  input wire logic [31:0] i_ch0, // 扩展后的组内起始通道
  input wire logic signed [p_coord_w-1:0] i_ix, // 当前输入水平坐标
  input wire logic signed [p_coord_w-1:0] i_iy, // 当前输入垂直坐标
  input wire logic [31:0] i_row_group_base, // 当前输出行的通道组字节基址
  input wire logic [31:0] i_next_row_group_base, // 下一输出行的通道组字节基址
  input wire logic [31:0] i_addr, // 当前运行通道的字节地址
  input wire logic [p_cache_read_width-1:0] i_word_buf, // 已经返回并保存的数据字
  input wire logic [31:0] i_word_addr, // 已经保存的数据字地址
  input wire logic i_word_valid, // 已经保存的数据字有效
  input wire logic i_incoming_word_hit, // 输入描述符命中可复用数据字
  input wire logic i_descriptor_response_forward, // 当前返回数据可直接供输入描述符使用
  input wire logic [1:0] i_incoming_tile_group_fits, // 窗口及当前通道起点满足输入描述符列范围
  input wire logic [15:0] i_last_output_col_q, // 输出末列的保存值
  input wire logic [15:0] i_last_kernel_col_q, // 卷积核末列的保存值
  input wire logic [p_cache_read_width-1:0] i_cache_rsp_data, // 当前缓存返回的数据字
  input wire logic i_pred_enabled, // 后续访问位置预测已启用
  input wire logic [31:0] i_groups_q, // 保存的通道组数量
  input wire logic i_geometry_tile, // 当前分块采用几何访问方式
  input wire logic i_incoming_tap_wrap, // 输入描述符在卷积核列方向回绕
  input wire logic [p_coord_w-1:0] i_bound_sum [7], // 各候选输入坐标的边界和值
  input wire logic [6:0] i_bound_valid, // 各候选坐标处于图像边界内
  input wire logic [2:0] i_skip_bound_valid, // 跳核候选坐标处于图像边界内
  input wire logic [2:0] i_window_padding, // 保存窗口的三个移动候选需要填充
  input wire logic signed [32:0] i_row_wrap_dx, // 输出行回绕的水平坐标增量
  input wire logic signed [32:0] i_tap_wrap_dx, // 卷积核回绕的水平坐标增量
  input wire logic signed [32:0] i_tap_wrap_pixels, // 卷积核回绕的像素增量
  input wire logic [31:0] i_row_step_bytes, // 相邻输出列的字节步长
  input wire logic [31:0] i_tap_step_bytes, // 相邻核列的字节步长
  input wire logic [31:0] i_row_wrap_bytes, // 输出列回绕的字节步长
  input wire logic [31:0] i_tap_wrap_bytes, // 核列回绕的字节步长
  input wire logic signed [p_coord_w-1:0] i_tap_pair_dx, // 相邻核行之间的水平坐标增量
  input wire logic [31:0] i_tap_pair_pixels, // 相邻核行之间的像素增量
  input wire logic [31:0] i_tap_pair_bytes, // 相邻核行之间的字节步长
  input wire logic i_row_base_valid, // 当前输出行的起点上下文有效
  input wire logic i_coordinate_address_valid, // 当前坐标对应的字节地址有效
  input wire logic signed [p_coord_w-1:0] i_row_base_ix, // 当前输出行起点的输入水平坐标
  input wire logic signed [p_coord_w-1:0] i_row_base_iy, // 当前输出行起点的输入垂直坐标
  input wire logic [31:0] i_row_base_pixel, // 当前输出行起点的像素位置
  input wire logic [31:0] i_row_base_addr, // 当前输出行起点的字节地址
  input wire logic i_row_wrap, // 当前输出列即将回绕
  input wire logic i_next_row_padding, // 下一输出行起点需要填充
  input wire logic i_row_next_o_equal, // 下一输出列是输出末列
  input wire logic signed [p_coord_w-1:0] i_next_row_ix, // 下一输出行起点的输入水平坐标
  input wire logic signed [p_coord_w-1:0] i_next_row_iy, // 下一输出行起点的输入垂直坐标
  input wire logic [31:0] i_next_row_pixel, // 下一输出行起点的像素位置
  input wire logic [31:0] i_next_row_addr, // 下一输出行起点的字节地址
  input wire logic i_tile_ready_context, // 当前运行上下文允许接收描述符
  output logic o_tile_rows_in_range, // 输入描述符的全部行处于空间范围内
  output logic o_tile_q_before_end, // 输入归约起点小于归约长度
  output logic [16:0] o_window_group_remaining_q, // 保存窗口起点的剩余通道数
  output logic o_incoming_next_tile_fast, // 输入描述符可直接继承下一空间分块位置
  output logic o_incoming_next_position_fast, // 输入描述符可复用下一空间窗口
  output logic o_incoming_skip_tap, // 输入描述符跳过一个卷积核位置
  output logic [15:0] o_window_next_x, // 保存窗口的输出列坐标
  output logic [15:0] o_window_next_y, // 保存窗口的输出行坐标
  output logic [15:0] o_window_next_ch, // 保存窗口的组内起始通道
  output logic o_incoming_fast, // 输入描述符可复用已准备的位置上下文
  output logic o_incoming_padding, // 输入描述符的首个位置需要填充
  output logic [31:0] o_incoming_ch, // 输入描述符的组内起始通道
  output logic [31:0] o_incoming_ky, // 输入描述符的卷积核行
  output logic [31:0] o_incoming_kx, // 输入描述符的卷积核列
  output logic [31:0] o_incoming_addr, // 输入描述符的首个字节地址
  output logic signed [p_coord_w-1:0] o_incoming_ix, // 输入描述符的输入水平坐标
  output logic signed [p_coord_w-1:0] o_incoming_iy, // 输入描述符的输入垂直坐标
  output logic [31:0] o_incoming_pixel, // 输入描述符的首个像素位置
  output logic [9:0][31:0] o_incoming_pixel_candidates, // 十种输入像素位置候选
  output logic [9:0][31:0] o_incoming_address_candidates, // 十种输入字节地址候选
  output logic [9:0][31:0] o_incoming_group_candidates, // 十种输入通道组地址候选
  output logic [9:0][15:0] o_incoming_kernel_x_candidates, // 十种输入卷积核列候选
  output logic [9:0][p_coord_w-1:0] o_incoming_y_candidates, // 十种输入垂直坐标候选
  output logic [9:0] o_incoming_pixel_select, // 输入位置候选的独热选择
  output logic o_incoming_word_o_equal, // 输入位置命中保存的数据字标签
  output logic o_incoming_live_word_o_equal, // 输入位置命中运行数据字标签
  output logic o_channel_accept_fire, // 当前周期接受快速描述符的通道状态
  output logic [p_prepared_tile_width-1:0] o_committing_tile_packed, // 当前提交的完整描述符字段
  output logic o_tile_prepared_valid, // 待提交描述符已经保存
  output logic o_tile_commit, // 当前周期提交一个描述符
  output logic o_committing_saved_word_hit, // 提交描述符命中其保存的数据字
  output logic o_committing_live_word_hit, // 提交描述符命中当前返回的数据字
  output logic o_descriptor_padding, // 提交描述符当前输入位置需要填充
  output logic [p_cache_read_width-1:0] o_descriptor_word_data_q, // 提交描述符保存的数据字内容
  output logic [1:0] o_next_row_word_match, // 下一行与保存字及运行字的标签匹配
  output logic [1:0] o_incoming_advanced_word_match, // 窗口分块及跳核候选的数据字匹配
  output logic [15:0] o_kernel_decode_column, // 按卷积核宽度掩码解出的核列
  output logic o_kernel_decode_last // 解出的核列为卷积核末列
);
  //! 0. 辅助信号
  //! -------------

  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
  logic [31:0] extent_i_tile_p0;
  logic [31:0] extent_i_tile_q0;
  logic [p_rw-1:0] extent_i_tile_rows;
  logic [31:0] extent_i_reduction_len;
  logic [31:0] extent_i_position_count;
  logic [p_row_high_w-1:0] extent_i_position_high_minus_one_q;
  logic extent_o_tile_rows_in_range;
  logic extent_o_tile_q_before_end;
  logic [31:0] incoming_group_base;
  logic incoming_same_position_fast;
  logic incoming_position_same_tap;
  logic incoming_position_forward_tap;
  logic incoming_position_backward_tap;
  logic incoming_position_previous_row;
  logic window_next_valid;
  logic window_next_padding;
  logic window_next_last_col;
  logic window_prepare_write;
  logic window_forward_allowed_q;
  logic window_backward_allowed_q;
  logic window_previous_allowed_q;
  logic [31:0] window_next_p;
  logic [31:0] window_next_q;
  logic [31:0] window_next_pixel;
  logic [31:0] window_next_addr;
  logic [31:0] window_next_group_base;
  logic [31:0] window_next_tap;
  logic [15:0] window_next_kx;
  logic [15:0] window_next_ky;
  logic [p_saved_group_lanes:0] window_next_channel_range;
  logic [31:0] next_position;
  logic [31:0] next_position_i_b;
  logic next_position_i_carry;
  logic next_position_o_equal;
  logic unused_next_position_carry;
  logic signed [p_coord_w-1:0] window_next_ix;
  logic signed [p_coord_w-1:0] window_next_iy;
  logic incoming_q_fast;
  logic incoming_group_fits;
  logic incoming_group_fits_reference;
  logic [31:0] incoming_tap;
  logic signed [p_coord_w-1:0] incoming_step_ix;
  logic signed [p_coord_w-1:0] incoming_wrap_ix;
  logic signed [p_coord_w-1:0] incoming_wrap_iy;
  logic incoming_base_padding;
  logic incoming_step_padding;
  logic incoming_wrap_padding;
  logic [31:0] incoming_pixel_next;
  logic [5:0] incoming_fast_i_flags;
  logic [1:0] incoming_position_equal;
  logic incoming_q_equal;
  logic [3:0] incoming_tap_match_o_equal;
  logic position_i_configure;
  logic position_i_commit;
  logic position_i_invalid;
  logic [31:0] position_i_commit_position;
  logic [p_tile_count_w-1:0] position_i_commit_rows;
  logic [31:0] position_i_position;
  logic [p_tile_count_w-1:0] position_i_rows;
  logic [31:0] position_i_target;
  logic position_o_equal;
  logic incoming_tile_match_o_equal;
  logic signed [p_coord_w-1:0] window_forward_ix;
  logic signed [p_coord_w-1:0] window_backward_ix;
  logic signed [p_coord_w-1:0] window_previous_iy;
  logic signed [p_coord_w-1:0] incoming_skip_ix;
  logic signed [p_coord_w-1:0] incoming_skip_iy;
  logic window_forward_padding;
  logic window_backward_padding;
  logic window_previous_padding;
  logic window_forward_padding_reference;
  logic window_backward_padding_reference;
  logic window_previous_padding_reference;
  logic incoming_skip_padding;
  logic window_shift_padding;
  logic channel_descriptor_valid;
  logic [5:0] channel_accept_i_flags;
  prepared_tile_t preparing_tile;
  prepared_tile_t prepared_tile_q;
  prepared_tile_t committing_tile;
  logic tile_capture;
  logic [p_cache_read_width-1:0] prepared_word_data;
  logic descriptor_padding_select_q;
  logic descriptor_padding_value_q;
  logic descriptor_saved_word_valid_q;
  logic [31-p_word_shift:0] descriptor_word_address_q;
  logic committing_saved_word_match;
  logic prepared_live_word_match;
  logic [8:0] prepared_padding_select;
  logic [8:0] prepared_padding_value;
  logic [9:0] prepared_word_select;
  localparam int p_incoming_data_width = 96 + 2*p_coord_w;
  logic [9:0][p_incoming_data_width-1:0] incoming_data_candidate;
  logic [p_incoming_data_width-1:0] incoming_data_selected;
  logic [9:0][63:0] incoming_kernel_values;
  logic [63:0] incoming_kernel_selected;
  logic [4:0][p_incoming_data_width-1:0] incoming_data_pair;
  logic incoming_padding_selected;
  logic incoming_padding_reference;
  logic incoming_window_context, incoming_window_match;
  logic incoming_window_position_match, incoming_single_row;
  logic incoming_next_tile_context;
  logic [9:0][5:0] incoming_word_flags;
  logic [8:0][5:0] incoming_padding_flags;
  logic [9:0] incoming_word_choice;
  logic [8:0] incoming_padding_choice;
  logic [1:0][31:0] prepared_address;
  logic signed [p_coord_w-1:0] prepared_coordinate_x;
  logic signed [p_coord_w-1:0] prepared_coordinate_y;
  logic [1:0] committing_coordinate_valid;
  logic [31:0] prepared_tap_base;
  logic [15:0] prepared_kernel_x_base;
  logic [15:0] prepared_kernel_y_base;
  logic [31:0] prepared_pixel_base;
  logic [p_tile_count_w-1:0] prepared_columns;
  logic [p_tile_count_w-1:0] prepared_active_columns;
  logic [31:0] descriptor_reduction;
  logic [p_tile_count_w-1:0] descriptor_columns;
  logic [32:0] prepared_next_group;
  logic [32:0] prepared_skip_group;
  logic [6:0][1:0][31:0] incoming_address_sum;
  logic [6:0][31:0] incoming_pixel_i_a;
  logic [6:0][31:0] incoming_pixel_i_b;
  logic [6:0] incoming_pixel_i_carry;
  logic [6:0][31:0] incoming_pixel_candidate;
  logic [6:0] unused_incoming_pixel_carry;
  logic [4:0][31:0] incoming_tap_i_a;
  logic [4:0][31:0] incoming_tap_i_b;
  logic [4:0][31:0] incoming_tap_candidate;
  logic [9:0][31:0] incoming_tap_values;
  logic [31:0] incoming_tap_selected;
  logic [4:0] unused_incoming_tap_carry;
  logic [2:0][32:0] incoming_compare_a;
  logic [2:0][32:0] incoming_compare_b;
  (* keep = "true" *) logic [2:0][10:0] incoming_part_equal;
  logic [2:0][1:0] incoming_group_equal;
  logic [16:0] negative_group;
  logic [2:0][32:0] target_difference;
  logic [2:0] target_difference_match;
  logic [2:0] target_prepared_match;
  logic [3:0] window_match_select;
  logic [6:0][p_coord_w-1:0] candidate_coordinate_sum;
  logic [6:0] candidate_coordinate_valid;
  logic incoming_kx_last;
  logic [15:0] kernel_decode_mask;
  logic [7:0] kernel_decode_column_equal;
  logic [p_prepared_tile_width-1:0] commit_i_prepared_tile_packed;
  logic [p_prepared_tile_width-1:0] commit_i_preparing_tile_packed;
  conv_im2col_pkg::conv_cfg_t commit_i_c;
  logic signed [32:0] commit_i_row_wrap_dx;
  logic signed [32:0] commit_i_tap_wrap_dx;
  logic signed [32:0] commit_i_tap_wrap_pixels;
  logic signed [p_coord_w-1:0] commit_i_tap_pair_dx;
  logic [31:0] commit_i_tap_pair_pixels;
  logic [31:0] commit_i_tap_step_bytes;
  logic [31:0] commit_i_tap_wrap_bytes;
  logic [31:0] commit_i_tap_pair_bytes;
  logic signed [p_coord_w-1:0] commit_i_ix;
  logic signed [p_coord_w-1:0] commit_i_iy;
  logic [15:0] commit_i_last_kernel_col_q;
  logic [p_tile_count_w-1:0] commit_i_active_columns;
  logic [32:0] commit_i_next_group;
  logic [32:0] commit_i_skip_group;
  logic [p_prepared_tile_width-1:0] commit_o_committing_tile_packed;
  logic [1:0] commit_o_coordinate_valid;
  logic [31:0] addresses_i_word_addr;
  logic [31:0] addresses_i_addr;
  logic [31:0] addresses_i_row_base_addr;
  logic [31:0] addresses_i_row_group_base;
  logic [31:0] addresses_i_window_addr;
  logic [31:0] addresses_i_window_group_base;
  logic [31:0] addresses_i_tap_step_bytes;
  logic [31:0] addresses_i_tap_wrap_bytes;
  logic [31:0] addresses_i_tap_pair_bytes;
  logic [31:0] addresses_i_row_step_bytes;
  logic [31:0] addresses_i_row_wrap_bytes;
  logic [31:0] addresses_i_next_row_addr;
  logic [15:0] addresses_i_kx0_q;
  logic addresses_i_row_wrap;
  logic addresses_i_incoming_tap_wrap;
  logic addresses_i_q_equal;
  logic addresses_i_position_previous_row;
  logic addresses_i_position_forward_tap;
  logic addresses_i_position_backward_tap;
  logic addresses_i_next_position_fast;
  logic addresses_i_next_tile_fast;
  logic [6:0][1:0][31:0] addresses_o_candidate_address;
  logic addresses_o_incoming_word_equal;
  logic addresses_o_incoming_live_word_equal;
  logic [1:0] addresses_o_next_row_word_match;
  logic [1:0] addresses_o_incoming_advanced_word_match;
  //! 1. 准备描述符字段
  //! -------------------

  assign o_committing_tile_packed = committing_tile;
  // 已保存归约位置同时用于组边界和有效列数，结果直接写入运行寄存器。
  assign descriptor_reduction = p_register_descriptor ? prepared_tile_q.reduction : i_tile_q0;
  assign descriptor_columns = p_register_descriptor ? prepared_tile_q.columns : prepared_columns;

  // 空间行范围和归约起点分别比较，接收条件直接读取各自结果。
  assign extent_i_tile_p0 = i_tile_p0;
  assign extent_i_tile_q0 = i_tile_q0;
  assign extent_i_tile_rows = i_tile_rows;
  assign extent_i_reduction_len = i_reduction_len;
  assign extent_i_position_count = i_position_count;
  assign extent_i_position_high_minus_one_q = i_position_high_minus_one_q;
  assign o_tile_rows_in_range = extent_o_tile_rows_in_range;
  assign o_tile_q_before_end = extent_o_tile_q_before_end;
  conv_descriptor_extent #(.p_rw(p_rw)) u_extent (
    .i_tile_p0(extent_i_tile_p0), .i_tile_q0(extent_i_tile_q0),
    .i_tile_rows(extent_i_tile_rows), .i_reduction_len(extent_i_reduction_len),
    .i_position_count(extent_i_position_count),
    .i_position_high_minus_one_q(extent_i_position_high_minus_one_q),
    .o_tile_rows_in_range(extent_o_tile_rows_in_range),
    .o_tile_q_before_end(extent_o_tile_q_before_end)
  );

  // 候选地址与字标签共用各自的起点和步长，接收控制只选择比较结果。
  assign addresses_i_word_addr = i_word_addr;
  assign addresses_i_addr = i_addr;
  assign addresses_i_row_base_addr = i_row_base_addr;
  assign addresses_i_row_group_base = i_row_group_base;
  assign addresses_i_window_addr = window_next_addr;
  assign addresses_i_window_group_base = window_next_group_base;
  assign addresses_i_tap_step_bytes = i_tap_step_bytes;
  assign addresses_i_tap_wrap_bytes = i_tap_wrap_bytes;
  assign addresses_i_tap_pair_bytes = i_tap_pair_bytes;
  assign addresses_i_row_step_bytes = i_row_step_bytes;
  assign addresses_i_row_wrap_bytes = i_row_wrap_bytes;
  assign addresses_i_next_row_addr = i_next_row_addr;
  assign addresses_i_kx0_q = i_kx0_q;
  assign addresses_i_row_wrap = i_row_wrap;
  assign addresses_i_incoming_tap_wrap = i_incoming_tap_wrap;
  assign addresses_i_q_equal = incoming_q_equal;
  assign addresses_i_position_previous_row = incoming_position_previous_row;
  assign addresses_i_position_forward_tap = incoming_position_forward_tap;
  assign addresses_i_position_backward_tap = incoming_position_backward_tap;
  assign addresses_i_next_position_fast = o_incoming_next_position_fast;
  assign addresses_i_next_tile_fast = o_incoming_next_tile_fast;
  assign incoming_address_sum = addresses_o_candidate_address;
  assign o_incoming_word_o_equal = addresses_o_incoming_word_equal;
  assign o_incoming_live_word_o_equal = addresses_o_incoming_live_word_equal;
  assign o_next_row_word_match = addresses_o_next_row_word_match;
  assign o_incoming_advanced_word_match = addresses_o_incoming_advanced_word_match;
  conv_descriptor_addresses #(
    .p_word_shift(p_word_shift), .p_register_descriptor(p_register_descriptor)
  ) u_addresses (
    .i_word_addr(addresses_i_word_addr),
    .i_addr(addresses_i_addr),
    .i_row_base_addr(addresses_i_row_base_addr),
    .i_row_group_base(addresses_i_row_group_base),
    .i_window_addr(addresses_i_window_addr),
    .i_window_group_base(addresses_i_window_group_base),
    .i_tap_step_bytes(addresses_i_tap_step_bytes),
    .i_tap_wrap_bytes(addresses_i_tap_wrap_bytes),
    .i_tap_pair_bytes(addresses_i_tap_pair_bytes),
    .i_row_step_bytes(addresses_i_row_step_bytes),
    .i_row_wrap_bytes(addresses_i_row_wrap_bytes),
    .i_next_row_addr(addresses_i_next_row_addr),
    .i_kx0_q(addresses_i_kx0_q),
    .i_row_wrap(addresses_i_row_wrap),
    .i_incoming_tap_wrap(addresses_i_incoming_tap_wrap),
    .i_q_equal(addresses_i_q_equal),
    .i_position_previous_row(addresses_i_position_previous_row),
    .i_position_forward_tap(addresses_i_position_forward_tap),
    .i_position_backward_tap(addresses_i_position_backward_tap),
    .i_next_position_fast(addresses_i_next_position_fast),
    .i_next_tile_fast(addresses_i_next_tile_fast),
    .o_candidate_address(addresses_o_candidate_address),
    .o_incoming_word_equal(addresses_o_incoming_word_equal),
    .o_incoming_live_word_equal(addresses_o_incoming_live_word_equal),
    .o_next_row_word_match(addresses_o_next_row_word_match),
    .o_incoming_advanced_word_match(addresses_o_incoming_advanced_word_match)
  );

  // 普通核步进和换行分别完成像素加法，换行条件只选择结果。
  assign incoming_pixel_next = i_incoming_tap_wrap ? incoming_pixel_candidate[5] : incoming_pixel_candidate[6];

  // 三种坐标的边界关系并行计算，描述符只选择已经完成的填充判断。
  assign incoming_step_ix = $signed(i_bound_sum[4]);
  assign incoming_wrap_ix = $signed(i_bound_sum[5]);
  assign incoming_wrap_iy = $signed(i_bound_sum[6]);
  assign incoming_base_padding = (|i_row_base_ix[p_coord_w-1:16]) || (|i_row_base_iy[p_coord_w-1:16]) ||
    i_row_base_ix[15:0] >= i_c.input_w || i_row_base_iy[15:0] >= i_c.input_h;
  assign incoming_step_padding = !i_bound_valid[4] || (|i_row_base_iy[p_coord_w-1:16]) ||
    i_row_base_iy[15:0] >= i_c.input_h;
  assign incoming_wrap_padding = !i_bound_valid[5] || !i_bound_valid[6];

  // 组内范围按描述符列数拆分，低位进位只选择已完成的高位关系。
  if (p_tile_count_w < 16) begin : g_incoming_group_range
    localparam int p_high_w = 16 - p_tile_count_w;
    logic [p_tile_count_w:0] column_end_low;
    logic high_before, high_equal, low_within, remaining_wrap;
    logic [p_high_w-1:0] high_next_i_a, high_next_i_b, high_next_i_target;
    logic high_next_i_carry_in, high_next_o_equal;

    assign column_end_low = {1'b0, i_ch0_q[p_tile_count_w-1:0]} + {1'b0, i_cols_q};
    assign high_before = i_ch0_q[15:p_tile_count_w] < i_c.group_c[15:p_tile_count_w];
    assign high_equal = i_ch0_q[15:p_tile_count_w] == i_c.group_c[15:p_tile_count_w];
    assign low_within = column_end_low[p_tile_count_w-1:0] <= i_c.group_c[p_tile_count_w-1:0];
    assign remaining_wrap = (!high_before && !high_equal) ||
      (high_equal && i_ch0_q[p_tile_count_w-1:0] > i_c.group_c[p_tile_count_w-1:0]);
    assign high_next_i_a = i_ch0_q[15:p_tile_count_w];
    assign high_next_i_b = '0;
    assign high_next_i_carry_in = 1'b1;
    assign high_next_i_target = i_c.group_c[15:p_tile_count_w];
    add_equal #(.p_width(p_high_w)) u_high_next (
      .i_a(high_next_i_a),
      .i_b(high_next_i_b),
      .i_carry_in(high_next_i_carry_in),
      .i_target(high_next_i_target),
      .o_equal(high_next_o_equal)
    );
    // 低位进位和高位关系并行合并，范围结果参与快速接收判断。
    assign incoming_group_fits_reference = remaining_wrap ||
      (high_before && (!column_end_low[p_tile_count_w] || !high_next_o_equal || low_within)) ||
      (high_equal && !column_end_low[p_tile_count_w] && low_within);
  end else begin : g_incoming_group_range_wide
    assign incoming_group_fits_reference = 32'(i_cols_q) <= 32'(i_c.group_c) - i_ch0;
  end

  // 组范围资格随已解出的通道或接收描述符保存，连续接收直接使用当前任务的结果。
  if (!p_register_descriptor && p_tile_count_w < 16) begin : g_saved_group_range
    logic fits_q;
    logic [1:0][15:0] candidate_channel;
    logic [1:0] candidate_fits;
    logic accepted_fits;

    assign candidate_channel = {o_window_next_ch, i_ch0_q};
    for (genvar source = 0; source < 2; source++) begin : g_candidate
      localparam int p_high_w = 16 - p_tile_count_w;
      logic [p_tile_count_w-1:0] remaining_low;
      logic low_borrow, high_before, high_equal, high_next_equal;
      logic remaining_wrap, all_columns_fit, candidate_fits_value;

      // 通道余量先按高低位并行求界，列数只参与低位阈值比较。
      assign remaining_low = i_c.group_c[p_tile_count_w-1:0] -
          candidate_channel[source][p_tile_count_w-1:0];
      assign low_borrow = i_c.group_c[p_tile_count_w-1:0] <
          candidate_channel[source][p_tile_count_w-1:0];
      assign high_before = candidate_channel[source][15:p_tile_count_w] <
          i_c.group_c[15:p_tile_count_w];
      assign high_equal = candidate_channel[source][15:p_tile_count_w] ==
          i_c.group_c[15:p_tile_count_w];
      add_equal #(.p_width(p_high_w)) u_high_next (
        .i_a(candidate_channel[source][15:p_tile_count_w]), .i_b({p_high_w{1'b0}}),
        .i_target(i_c.group_c[15:p_tile_count_w]), .i_carry_in(1'b1),
        .o_equal(high_next_equal)
      );
      assign remaining_wrap = (!high_before && !high_equal) || (high_equal && low_borrow);
      assign all_columns_fit = remaining_wrap ||
          (high_before && (!low_borrow || !high_next_equal));
      assign candidate_fits_value = all_columns_fit || prepared_columns <= remaining_low;
`ifdef SYNTHESIS
      assign candidate_fits[source] = candidate_fits_value;
`else
      logic [16:0] candidate_end;
      assign candidate_end = {1'b0, candidate_channel[source]} + 17'(prepared_columns);
      // 未知输入保留完整加法和关系运算的事件仿真传播。
      always_comb begin
        case (^{candidate_channel[source], prepared_columns, i_c.group_c})
          1'b0, 1'b1: candidate_fits[source] = candidate_fits_value;
          default: candidate_fits[source] = i_c.group_c < candidate_channel[source] ||
              candidate_end <= {1'b0, i_c.group_c};
        endcase
      end
`endif
    end
    always_comb begin
      accepted_fits = candidate_fits[0];
      if (o_incoming_next_position_fast) accepted_fits = candidate_fits[1];
    end
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) fits_q <= 1'b0;
      else if (i_cfg_valid && i_cfg_ready) fits_q <= 1'b0;
      else if (o_tile_commit) begin
        if (!channel_descriptor_valid) begin end
        else fits_q <= accepted_fits;
      end
      else if (i_state[$clog2(K_DECODE)]) fits_q <= incoming_group_fits_reference;
    end
`ifdef SYNTHESIS
    assign incoming_group_fits = fits_q;
`else
    always_comb begin
      case (^{i_ch0_q, i_cols_q, i_c.group_c})
        1'b0, 1'b1: incoming_group_fits = fits_q;
        default: incoming_group_fits = incoming_group_fits_reference;
      endcase
    end
`endif
`ifdef NPU_SIM_ASSERT
    always @(posedge i_clk) begin
      if (i_rst_n && i_row_base_valid && i_coordinate_address_valid)
        assert (fits_q == incoming_group_fits_reference);
    end
`endif
  end else begin : g_direct_group_range
    assign incoming_group_fits = incoming_group_fits_reference;
  end

  // 像素候选以四位分组并行求进位，候选选择保留完整三十二位模结果。
  assign incoming_pixel_i_a = {i_row_base_pixel, i_row_base_pixel, i_row_base_pixel,
    i_row_base_pixel, window_next_pixel, window_next_pixel, window_next_pixel};
  assign incoming_pixel_i_b[0] = ~i_tap_pair_pixels;
  assign incoming_pixel_i_b[1] = 32'(i_c.dilation_w);
  assign incoming_pixel_i_b[2] = ~32'(i_c.dilation_w);
  assign incoming_pixel_i_b[3] = i_tap_pair_pixels;
  assign incoming_pixel_i_b[4] = 32'(i_c.dilation_w) << 1;
  assign incoming_pixel_i_b[5] = 32'($unsigned(i_tap_wrap_pixels));
  assign incoming_pixel_i_b[6] = 32'(i_c.dilation_w);
  assign incoming_pixel_i_carry = 7'b0000101;
  for (genvar candidate = 0; candidate < 7; candidate++) begin : g_incoming_pixel
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_sum (
      .i_a(incoming_pixel_i_a[candidate]), .i_b(incoming_pixel_i_b[candidate]),
      .i_carry(incoming_pixel_i_carry[candidate]), .o_sum(incoming_pixel_candidate[candidate]),
      .o_carry(unused_incoming_pixel_carry[candidate])
    );
  end

  // 核位置的正负常量步进并行计算，描述符控制不进入进位计算。
  assign incoming_tap_i_a = {i_tap0, i_tap0, window_next_tap, window_next_tap, window_next_tap};
  assign incoming_tap_i_b = {32'd1, 32'd2, 32'hffff_ffff, 32'd1, 32'hffff_fffe};
  for (genvar candidate = 0; candidate < 5; candidate++) begin : g_incoming_tap
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_sum (
      .i_a(incoming_tap_i_a[candidate]), .i_b(incoming_tap_i_b[candidate]), .i_carry(1'b0),
      .o_sum(incoming_tap_candidate[candidate]), .o_carry(unused_incoming_tap_carry[candidate])
    );
  end

  // 描述符字段分组比较，步长和低位进位使用同一个接收条件。

  assign incoming_compare_a[0] = {1'b0, i_tile_p0};
  assign incoming_compare_a[1] = {1'b0, i_tile_q0};
  assign incoming_compare_a[2] = {1'b0, i_tile_q0};
  assign incoming_compare_b[0] = {1'b0, i_p0};
  assign incoming_compare_b[1] = {1'b0, i_q0};
  assign incoming_compare_b[2] = i_next_group_q;
  for (genvar value = 0; value < 3; value++) begin : g_incoming_compare
    for (genvar part = 0; part < 11; part++) begin : g_part
      assign incoming_part_equal[value][part] =
        incoming_compare_a[value][3*part +: 3] == incoming_compare_b[value][3*part +: 3];
    end
    assign incoming_group_equal[value][0] = &incoming_part_equal[value][5:0];
    assign incoming_group_equal[value][1] = &incoming_part_equal[value][10:6];
  end
  assign incoming_position_equal = incoming_group_equal[0];
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_current_reduction_match (
    .i_a(i_tile_q0), .i_b(i_q0), .o_equal(incoming_q_equal)
  );
  // 两个核位置的目标序号随描述符保存，后续接收直接比较目标序号。
  conv_descriptor_match #(.p_width(33), .p_preserve_groups(1'b1)) u_skip_reduction_match (
    .i_a(i_skip_group_q), .i_b({1'b0, i_tile_q0}), .o_equal(incoming_tap_match_o_equal[0])
  );

`ifndef SYNTHESIS
  logic [32:0] reduction_difference;
  assign reduction_difference = {1'b0, i_tile_q0} - {1'b0, window_next_q};
`endif
  // 相邻核位置只需要三种步长的相等条件，各位并行检查完整三十三位进位关系。
  // 配置保存的组末值直接构造负步长，最高位保留跨三十二位边界的区别。
  assign negative_group = {i_group_nonzero_q, ~i_last_group_channel_q};
  assign target_difference[0] = {17'd0, i_c.group_c};
  assign target_difference[1] = {{16{negative_group[16]}}, negative_group};
  assign target_difference[2] = {{15{negative_group[16]}}, negative_group, 1'b0};
  for (genvar target = 0; target < 3; target++) begin : g_target
    if (!p_register_descriptor) begin : g_prepared
      logic [32:0] target_sum, target_q;
      logic unused_target_carry;
      logic target_eligible, target_eligible_nxt, target_low_equal;

      // 窗口起点和三个完整目标序号同时保存，接收周期直接比较目标值。
      parallel_prefix_add #(.p_width(33), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_sum (
        .i_a({1'b0, i_q0}), .i_b(target_difference[target]), .i_carry(1'b0),
        .o_sum(target_sum), .o_carry(unused_target_carry)
      );
      // 目标高位越界与核位置许可在目标保存前合并，查询只比较完整低三十二位。
      assign target_eligible_nxt = !target_sum[32] &&
          (target == 0 ? i_kx0_q < i_last_kernel_col_q :
           target == 1 ? i_kx0_q != 16'd0 :
           i_c.kernel_w == 16'd3 && i_kx0_q == 16'd0 && i_ky0_q != 16'd0);
      always_ff @(posedge i_clk) begin
        if (i_rst_n && window_prepare_write) begin
          target_q <= target_sum;
          target_eligible <= target_eligible_nxt;
        end
      end
      conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_target_low_match (
        .i_a(target_q[31:0]), .i_b(i_tile_q0), .o_equal(target_low_equal)
      );
      assign target_prepared_match[target] = target_eligible && target_low_equal;
      conv_descriptor_match #(.p_width(33), .p_preserve_groups(1'b1)) u_target_match (
        .i_a(target_q), .i_b({1'b0, i_tile_q0}), .o_equal(target_difference_match[target])
      );
`ifdef NPU_SIM_ASSERT
      always @(posedge i_clk) begin
        if (i_rst_n && window_next_valid) begin
          assert (target_q == {1'b0, window_next_q} + target_difference[target]);
          assert (target_eligible == (!target_q[32] &&
              (target == 0 ? window_forward_allowed_q :
               target == 1 ? window_backward_allowed_q : window_previous_allowed_q)));
        end
      end
`endif
    end else begin : g_direct
      conv_descriptor_window_target u_match (
        .i_clk(i_clk), .i_write(i_rst_n && window_prepare_write),
        .i_preparing_reduction(i_q0), .i_saved_reduction(window_next_q),
        .i_step(target_difference[target]), .i_target(i_tile_q0),
        .o_equal(target_difference_match[target])
      );
      assign target_prepared_match[target] = target_difference_match[target];
    end
`ifdef SYNTHESIS
    assign incoming_tap_match_o_equal[target+1] = target_prepared_match[target];
`else
    // 未知输入保留完整减法和相等比较的事件仿真传播。
    always_comb begin
      case (^{i_tile_q0, window_next_q, target_difference[target]})
        1'b0, 1'b1: incoming_tap_match_o_equal[target+1] = target_difference_match[target];
        default: incoming_tap_match_o_equal[target+1] = reduction_difference == target_difference[target];
      endcase
    end
`endif
  end
  // 下一空间起点与当前描述符同边沿更新，待接收位置只进入相等比较。
  assign position_i_configure = i_cfg_valid && i_cfg_ready;
  assign position_i_commit = o_tile_commit;
  assign position_i_invalid = committing_tile.invalid;
  assign position_i_commit_position = committing_tile.position;
  assign position_i_commit_rows = committing_tile.rows;
  assign position_i_position = i_p0;
  assign position_i_rows = i_rows_q;
  assign position_i_target = i_tile_p0;
  assign incoming_tile_match_o_equal = position_o_equal;
  conv_descriptor_position #(.p_count_width(p_tile_count_w)) u_position (
    .clk(i_clk), .rst_n(i_rst_n),
    .i_configure(position_i_configure), .i_commit(position_i_commit),
    .i_invalid(position_i_invalid), .i_commit_position(position_i_commit_position),
    .i_commit_rows(position_i_commit_rows), .i_position(position_i_position),
    .i_rows(position_i_rows), .i_target(position_i_target), .o_equal(position_o_equal)
  );
  assign o_incoming_skip_tap = i_c.kernel_w == 16'd3 && incoming_tap_match_o_equal[0];
  assign incoming_q_fast = incoming_q_equal || (&incoming_group_equal[2]) || o_incoming_skip_tap;
  // 坐标资格与单行条件提前合并，晚到的组范围保持单级接收选择。
  assign incoming_fast_i_flags[0] = i_c.windowed && i_row_base_valid && i_coordinate_address_valid;
  assign incoming_fast_i_flags[1] = i_rows_q == p_tile_count_w'(1) && i_tile_rows == p_rw'(1);
  assign incoming_fast_i_flags[2] = incoming_group_fits;
  assign incoming_fast_i_flags[4:3] = incoming_position_equal;
  assign incoming_fast_i_flags[5] = incoming_q_fast;
  assign incoming_same_position_fast = p_cache_policy == 3 && (&incoming_fast_i_flags);
  // 相邻空间位置可从同一核行的前后一个有效位置开始，列边界只调整水平步长。
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_window_reduction_match (
    .i_a(i_tile_q0), .i_b(window_next_q), .o_equal(incoming_position_same_tap)
  );
  // 直接描述符使用同一准备边沿保存的许可；寄存描述符继续按原窗口状态选择。
`ifdef SYNTHESIS
  assign window_match_select = p_register_descriptor ?
      {window_previous_allowed_q, window_backward_allowed_q, window_forward_allowed_q, 1'b1} : 4'b1111;
`else
  assign window_match_select =
      {window_previous_allowed_q, window_backward_allowed_q, window_forward_allowed_q, 1'b1};
`endif
  assign incoming_position_forward_tap = window_match_select[1] &&
      incoming_tap_match_o_equal[1];
  assign incoming_position_backward_tap = window_match_select[2] &&
      incoming_tap_match_o_equal[2];
  // 三列卷积从顶部边缘进入下一输出行时，首个有效核位置向前移动两个位置。
  assign incoming_position_previous_row = window_match_select[3] &&
      incoming_tap_match_o_equal[3];
  // 完整坐标比较先独立完成，运行资格只归并各比较的一位结果。
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_window_position_match (
    .i_a(i_tile_p0), .i_b(window_next_p), .o_equal(incoming_window_position_match)
  );
  conv_descriptor_match #(.p_width(p_rw)) u_single_row_match (
    .i_a(i_tile_rows), .i_b(p_rw'(1)), .o_equal(incoming_single_row)
  );
  conv_descriptor_qualify #(.p_flags(6)) u_window_context (
    .i_flags({p_cache_policy == 3, i_c.windowed, window_next_valid,
              incoming_single_row, incoming_window_position_match, i_incoming_tile_group_fits[0]}),
    .i_window(2'b00), .o_valid(incoming_window_context)
  );
  onehot_mux #(.p_choices(4), .p_width(1)) u_window_match (
    .i_select(window_match_select),
    .i_data({incoming_tap_match_o_equal[3:1], incoming_position_same_tap}),
    .o_data(incoming_window_match)
  );
  assign o_incoming_next_position_fast = incoming_window_context && incoming_window_match;
  // 连续空间分块继承末行的下一坐标，归约起点变化时继续执行通用解码。
  assign incoming_next_tile_context = p_cache_policy == 3 && i_c.windowed && !i_geometry_tile &&
      i_row_base_valid && i_coordinate_address_valid;
  conv_descriptor_qualify #(.p_flags(4)) u_next_tile_context (
    .i_flags({incoming_next_tile_context, incoming_q_equal,
              incoming_tile_match_o_equal, i_incoming_tile_group_fits[1]}),
    .i_window(2'b00), .o_valid(o_incoming_next_tile_fast)
  );
  // 空间窗口和另外两种快速来源并行归并，窗口资格在这一层参与选择。
  onehot_mux #(.p_choices(3), .p_width(1)) u_incoming_fast (
    .i_select({1'b1, 1'b1, incoming_window_context}),
    .i_data({incoming_same_position_fast, o_incoming_next_tile_fast, incoming_window_match}),
    .o_data(o_incoming_fast)
  );

  // 位置递增和保存值的匹配并行计算，更新条件直接使用进位一致性比较。
  assign next_position_i_b = 32'd0;
  assign next_position_i_carry = 1'b1;
  add_equal #(.p_width(32)) u_next_position_match (
    .i_a(i_p0), .i_b(next_position_i_b), .i_target(window_next_p),
    .i_carry_in(next_position_i_carry), .o_equal(next_position_o_equal)
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_next_position (
    .i_a(i_p0), .i_b(next_position_i_b), .i_carry(next_position_i_carry),
    .o_sum(next_position), .o_carry(unused_next_position_carry)
  );

  // 窗口有效状态使用异步复位，坐标和地址只在准备事件的时钟边沿保存。
  always_comb begin
    window_prepare_write = 1'b0;
    if (i_cfg_valid && i_cfg_ready) begin
    end else if (i_rows_q == p_tile_count_w'(1) && i_row_base_valid &&
                 i_coordinate_address_valid && (i_state[$clog2(FETCH)] || i_state[$clog2(WAIT_WORD)] ||
                 i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]) &&
                 (!window_next_valid || !next_position_o_equal)) begin
      window_prepare_write = 1'b1;
    end
  end
  if (!p_register_descriptor) begin : g_direct_candidate_geometry
  logic [6:0][p_coord_w-1:0] candidate_coordinate_i_a, candidate_coordinate_i_b;
  logic [6:0] candidate_coordinate_carry, unused_candidate_coordinate_carry;
  assign candidate_coordinate_i_a = {i_row_base_iy, i_row_base_ix, i_row_base_iy, i_row_base_ix, window_next_iy, window_next_ix, window_next_ix};
  assign candidate_coordinate_i_b[0] = p_coord_w'(i_c.dilation_w);
  assign candidate_coordinate_i_b[1] = ~p_coord_w'(i_c.dilation_w);
  assign candidate_coordinate_i_b[2] = ~p_coord_w'(i_c.dilation_h);
  assign candidate_coordinate_i_b[3] = i_tap_pair_dx;
  assign candidate_coordinate_i_b[4] = p_coord_w'(i_c.dilation_h);
  assign candidate_coordinate_i_b[5] = p_coord_w'(i_c.dilation_w) << 1;
  assign candidate_coordinate_i_b[6] = '0;
  assign candidate_coordinate_carry = 7'b0000110;
  for (genvar source = 0; source < 7; source++) begin : g_candidate_coordinate
    logic [p_coord_w-1:0] sum_i_a, sum_i_b;
    assign sum_i_a = candidate_coordinate_i_a[source];
    assign sum_i_b = candidate_coordinate_i_b[source];
    parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(8), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_sum (
      .i_a(sum_i_a), .i_b(sum_i_b), .i_carry(candidate_coordinate_carry[source]),
      .o_sum(candidate_coordinate_sum[source]), .o_carry(unused_candidate_coordinate_carry[source])
    );
  end

  for (genvar axis = 0; axis < 7; axis++) begin : g_candidate_bound
    logic [15:0] coordinate_limit;
    logic [8:0] low_byte, high_zero, high_one;
    logic low_before, high_zero_before, high_one_before;
    logic high_zero_equal, high_one_equal, high_carry, high_equal;
    logic [p_coord_w-17:0] high_i_a, high_i_b, high_i_target;
    logic low_carry;

    // 高字节的两种进位结果及比较并行完成，高位仅检查模加结果是否为零。
    assign coordinate_limit = axis == 2 || axis == 4 || axis == 6 ? i_c.input_h : i_c.input_w;
    assign low_byte = {1'b0, candidate_coordinate_i_a[axis][7:0]} +
      {1'b0, candidate_coordinate_i_b[axis][7:0]} + 9'(candidate_coordinate_carry[axis]);
    assign high_zero = {1'b0, candidate_coordinate_i_a[axis][15:8]} +
      {1'b0, candidate_coordinate_i_b[axis][15:8]};
    assign high_one = ~(~{1'b0, candidate_coordinate_i_a[axis][15:8]} +
      ~{1'b0, candidate_coordinate_i_b[axis][15:8]});
    assign low_before = low_byte[7:0] < coordinate_limit[7:0];
    assign high_zero_before = high_zero[7:0] < coordinate_limit[15:8] ||
      (high_zero[7:0] == coordinate_limit[15:8] && low_before);
    assign high_one_before = high_one[7:0] < coordinate_limit[15:8] ||
      (high_one[7:0] == coordinate_limit[15:8] && low_before);
    assign low_carry = low_byte[8];
    assign high_carry = low_carry ? high_one[8] : high_zero[8];
    assign high_i_a = candidate_coordinate_i_a[axis][p_coord_w-1:16];
    assign high_i_b = candidate_coordinate_i_b[axis][p_coord_w-1:16];
    assign high_i_target = '0;
    add_equal #(.p_width(p_coord_w-16)) u_high_zero (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_carry), .o_equal(high_equal)
    );
    if (axis >= 3) begin : g_current
      logic prepared_valid;
      assign prepared_valid = axis == 3 ? i_skip_bound_valid[0] : axis == 4 ? i_bound_valid[6] :
          axis == 5 ? i_skip_bound_valid[1] : i_skip_bound_valid[2];
`ifdef SYNTHESIS
      assign candidate_coordinate_valid[axis] = prepared_valid;
`else
      always_comb begin
        case (^{candidate_coordinate_i_a[axis], candidate_coordinate_i_b[axis], coordinate_limit})
          1'b0, 1'b1: candidate_coordinate_valid[axis] = prepared_valid;
          default: candidate_coordinate_valid[axis] = high_equal &&
              (low_carry ? high_one_before : high_zero_before);
        endcase
      end
`endif
`ifdef NPU_SIM_ASSERT
      always @(posedge i_clk) begin
        if (i_rst_n && i_row_base_valid && i_coordinate_address_valid)
          assert (prepared_valid == (high_equal && (low_carry ? high_one_before : high_zero_before)));
      end
`endif
    end else begin : g_window
    assign candidate_coordinate_valid[axis] = high_equal &&
      (low_carry ? high_one_before : high_zero_before);
    end
  end
  end else begin : g_saved_candidate_geometry
    // 描述符保存坐标操作数，提交阶段共用两个坐标求和与范围检查。
    assign candidate_coordinate_sum = '0;
    assign candidate_coordinate_valid = '0;
  end

  if (!p_register_descriptor) begin : g_direct_kernel_end
  logic [3:0][15:0] incoming_kernel_i_a, incoming_kernel_i_target;
  logic [15:0] incoming_kernel_i_b;
  logic incoming_kernel_i_carry;
  logic [3:0] incoming_kernel_o_equal;
  logic incoming_window_kx_last, incoming_skip_kx_last, incoming_base_kx_last;
  logic incoming_kernel_last_reference, incoming_kernel_last_selected;
  logic [9:0] incoming_kernel_last_candidate;
  assign incoming_kernel_i_a = {i_last_kernel_col_q, i_kx0_q, i_last_kernel_col_q, window_next_kx};
  assign incoming_kernel_i_target = {i_kx0_q, i_last_kernel_col_q, window_next_kx, i_last_kernel_col_q};
  assign incoming_kernel_i_b = 16'd0;
  assign incoming_kernel_i_carry = 1'b1;
  for (genvar candidate = 0; candidate < 4; candidate++) begin : g_incoming_kernel_end
    add_equal #(.p_width(16)) u_match (
      .i_a(incoming_kernel_i_a[candidate]), .i_b(incoming_kernel_i_b),
      .i_target(incoming_kernel_i_target[candidate]), .i_carry_in(incoming_kernel_i_carry),
      .o_equal(incoming_kernel_o_equal[candidate])
    );
  end
  // 候选核列直接生成末列标志，描述符选择只合并一位结果。
  assign incoming_base_kx_last = i_kx0_q == i_last_kernel_col_q;
  assign incoming_window_kx_last = incoming_position_previous_row ? i_last_kernel_col_q == 16'd1 :
    incoming_position_forward_tap ? incoming_kernel_o_equal[0] :
    incoming_position_backward_tap ? incoming_kernel_o_equal[1] : window_next_kx == i_last_kernel_col_q;
  assign incoming_skip_kx_last = i_kx0_q != 16'd0 ? incoming_kernel_o_equal[3] : i_last_kernel_col_q == 16'd2;
  assign incoming_kernel_last_reference = o_incoming_next_position_fast ? incoming_window_kx_last :
    o_incoming_next_tile_fast ? incoming_base_kx_last : o_incoming_skip_tap ? incoming_skip_kx_last :
    !incoming_q_equal ? (i_incoming_tap_wrap ? i_last_kernel_col_q == 16'd0 : incoming_kernel_o_equal[2]) :
    incoming_base_kx_last;
  // 每种位置先形成末列标志，核列与地址共用同一独热候选选择。
  assign incoming_kernel_last_candidate = {
    i_last_kernel_col_q == 16'd1,
    incoming_kernel_o_equal[1], incoming_kernel_o_equal[0],
    window_next_kx == i_last_kernel_col_q, incoming_base_kx_last,
    incoming_kernel_o_equal[3], i_last_kernel_col_q == 16'd2,
    i_last_kernel_col_q == 16'd0, incoming_kernel_o_equal[2], incoming_base_kx_last};
  onehot_mux #(.p_choices(10), .p_width(1)) u_kernel_last (
    .i_select(prepared_word_select), .i_data(incoming_kernel_last_candidate),
    .o_data(incoming_kernel_last_selected)
  );
  always_comb begin
    incoming_kx_last = incoming_kernel_last_reference;
    case (^{prepared_word_select, incoming_kernel_last_candidate,
        o_incoming_next_position_fast, o_incoming_next_tile_fast, o_incoming_skip_tap,
        incoming_q_equal, i_incoming_tap_wrap, incoming_position_previous_row,
        incoming_position_forward_tap, incoming_position_backward_tap, i_kx0_q,
        window_next_kx, i_last_kernel_col_q})
      1'b0, 1'b1: incoming_kx_last = incoming_kernel_last_selected;
      default: begin end
    endcase
  end

  end else begin : g_saved_kernel_end
    assign incoming_kx_last = 1'b0;
  end

  assign kernel_decode_mask = i_last_kernel_col_q;
  assign o_kernel_decode_column = i_tap0[15:0] & kernel_decode_mask;
  // 两位掩码坐标与目标同时比较，各组独立后再归并。
  for (genvar group_index = 0; group_index < 8; group_index++) begin : g_kernel_decode_end
    assign kernel_decode_column_equal[group_index] =
        o_kernel_decode_column[group_index*2 +: 2] == i_last_kernel_col_q[group_index*2 +: 2];
  end
  assign o_kernel_decode_last = &kernel_decode_column_equal;

  // 各候选坐标和填充状态独立计算，晚到的描述符仅选择计算结果。
  // 高位检查保留完整的有符号坐标范围，低十六位比较有效图像尺寸。
  assign window_forward_ix = $signed(candidate_coordinate_sum[0]);
  assign window_backward_ix = $signed(candidate_coordinate_sum[1]);
  assign window_previous_iy = $signed(candidate_coordinate_sum[2]);
  assign window_forward_padding_reference = !candidate_coordinate_valid[0] ||
    (|window_next_iy[p_coord_w-1:16]) || window_next_iy[15:0] >= i_c.input_h;
  assign window_backward_padding_reference = !candidate_coordinate_valid[1] ||
    (|window_next_iy[p_coord_w-1:16]) || window_next_iy[15:0] >= i_c.input_h;
  assign window_previous_padding_reference = !candidate_coordinate_valid[0] || !candidate_coordinate_valid[2];
  if (!p_register_descriptor) begin : g_saved_window_padding
    logic [2:0] padding_q;
    always_ff @(posedge i_clk) begin
      if (i_rst_n && window_prepare_write) padding_q <= i_window_padding;
    end
`ifdef SYNTHESIS
    assign {window_previous_padding, window_backward_padding, window_forward_padding} = padding_q;
`else
    always_comb begin
      case (^{window_next_ix, window_next_iy, i_c.dilation_w, i_c.dilation_h, i_c.input_w, i_c.input_h})
        1'b0, 1'b1: {window_previous_padding, window_backward_padding, window_forward_padding} = padding_q;
        default: {window_previous_padding, window_backward_padding, window_forward_padding} =
            {window_previous_padding_reference, window_backward_padding_reference, window_forward_padding_reference};
      endcase
    end
`endif
`ifdef NPU_SIM_ASSERT
    always @(posedge i_clk) begin
      if (i_rst_n && window_next_valid)
        assert (padding_q == {window_previous_padding_reference, window_backward_padding_reference,
                             window_forward_padding_reference});
    end
`endif
  end else begin : g_direct_window_padding
    assign window_previous_padding = window_previous_padding_reference;
    assign window_backward_padding = window_backward_padding_reference;
    assign window_forward_padding = window_forward_padding_reference;
  end
  assign incoming_skip_ix = $signed(i_kx0_q != 16'd0 ? candidate_coordinate_sum[3] : candidate_coordinate_sum[5]);
  assign incoming_skip_iy = $signed(i_kx0_q != 16'd0 ? candidate_coordinate_sum[4] : candidate_coordinate_sum[6]);
  // 两种跳核坐标并行检查边界，核列状态只选择最终的填充标志。
  assign incoming_skip_padding = i_kx0_q != 16'd0 ?
    (!candidate_coordinate_valid[3] || !candidate_coordinate_valid[4]) :
    (!candidate_coordinate_valid[5] || !candidate_coordinate_valid[6]);
  // 同核位置保留已保存的填充标志，其余候选维持前一行、前向、后向的选择次序。
  assign window_shift_padding = incoming_position_same_tap ? window_next_padding :
    incoming_position_previous_row ? window_previous_padding :
    incoming_position_forward_tap ? window_forward_padding : window_backward_padding;

  always_comb begin
    incoming_tap=i_tap0;o_incoming_ch=i_ch0;o_incoming_kx=i_kx0;o_incoming_ky=i_ky0;
    o_incoming_ix=i_row_base_ix;o_incoming_iy=i_row_base_iy;
    o_incoming_pixel=i_row_base_pixel;o_incoming_addr=i_row_base_addr;incoming_group_base=i_row_group_base;
    incoming_padding_reference=incoming_base_padding;
    if (o_incoming_next_position_fast) begin
      incoming_tap=window_next_tap;o_incoming_ch={16'd0,o_window_next_ch};
      o_incoming_kx={16'd0,window_next_kx};o_incoming_ky={16'd0,window_next_ky};
      o_incoming_ix=window_next_ix;o_incoming_iy=window_next_iy;
      o_incoming_pixel=window_next_pixel;o_incoming_addr=window_next_addr;
      incoming_group_base=window_next_group_base;incoming_padding_reference=window_shift_padding;
      if (incoming_position_previous_row) begin
        incoming_tap=incoming_tap_candidate[0];
        o_incoming_kx=32'd1;o_incoming_ky={16'd0,window_next_ky}-32'd1;
        o_incoming_ix=window_forward_ix;
        o_incoming_iy=window_previous_iy;
        o_incoming_pixel=incoming_pixel_candidate[0];
        o_incoming_addr=incoming_address_sum[6][0];
        incoming_group_base=incoming_address_sum[6][1];
      end else if (incoming_position_forward_tap) begin
        incoming_tap=incoming_tap_candidate[1];o_incoming_kx={16'd0,window_next_kx}+32'd1;
        o_incoming_ix=window_forward_ix;
        o_incoming_pixel=incoming_pixel_candidate[1];
        o_incoming_addr=incoming_address_sum[4][0];
        incoming_group_base=incoming_address_sum[4][1];
      end else if (incoming_position_backward_tap) begin
        incoming_tap=incoming_tap_candidate[2];o_incoming_kx={16'd0,window_next_kx}-32'd1;
        o_incoming_ix=window_backward_ix;
        o_incoming_pixel=incoming_pixel_candidate[2];
        o_incoming_addr=incoming_address_sum[5][0];
        incoming_group_base=incoming_address_sum[5][1];
      end
    end else if (o_incoming_next_tile_fast) begin
      o_incoming_ix=i_next_row_ix;o_incoming_iy=i_next_row_iy;
      o_incoming_pixel=i_next_row_pixel;o_incoming_addr=i_next_row_addr;
      incoming_group_base=i_next_row_group_base;incoming_padding_reference=i_next_row_padding;
    end else if (o_incoming_skip_tap) begin
      incoming_tap=incoming_tap_candidate[3];
      o_incoming_ix=incoming_skip_ix;o_incoming_iy=incoming_skip_iy;
      incoming_padding_reference=incoming_skip_padding;
      if (i_kx0_q!=16'd0) begin
        o_incoming_kx=i_kx0-32'd1;o_incoming_ky=i_ky0+32'd1;
        o_incoming_pixel=incoming_pixel_candidate[3];
        o_incoming_addr=incoming_address_sum[3][0];
        incoming_group_base=incoming_address_sum[3][1];
      end else begin
        o_incoming_kx=32'd2;
        o_incoming_pixel=incoming_pixel_candidate[4];
        o_incoming_addr=incoming_address_sum[2][0];
        incoming_group_base=incoming_address_sum[2][1];
      end
    end else if (!incoming_q_equal) begin
      incoming_tap=incoming_tap_candidate[4];
      if (i_incoming_tap_wrap) begin
        o_incoming_kx=0;o_incoming_ky=i_ky0+1;
        o_incoming_ix=incoming_wrap_ix;
        o_incoming_iy=incoming_wrap_iy;
        o_incoming_pixel=incoming_pixel_next;
        o_incoming_addr=incoming_address_sum[1][0];incoming_group_base=incoming_address_sum[1][1];
        incoming_padding_reference=incoming_wrap_padding;
      end else begin
        o_incoming_kx=i_kx0+1;
        o_incoming_ix=incoming_step_ix;
        o_incoming_pixel=incoming_pixel_next;
        o_incoming_addr=incoming_address_sum[0][0];incoming_group_base=incoming_address_sum[0][1];
        incoming_padding_reference=incoming_step_padding;
      end
    end
`ifdef SYNTHESIS
    if (!p_register_descriptor) begin
      incoming_tap = incoming_tap_selected;
      {o_incoming_ky, o_incoming_kx} = incoming_kernel_selected;
      {o_incoming_ix, o_incoming_iy, o_incoming_pixel, incoming_group_base, o_incoming_addr} = incoming_data_selected;
    end
`endif
  end

`ifdef SYNTHESIS
  assign o_incoming_padding = p_register_descriptor ? incoming_padding_reference : incoming_padding_selected;
`else
  assign o_incoming_padding = incoming_padding_reference;
`endif

  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。
  // 描述符准备和状态提交分开保存，候选算术在专用寄存器前完成。
  assign prepared_columns = i_tile_cols == '0 ? p_tile_count_w'(p_size) : p_tile_count_w'(i_tile_cols);
  if (p_tile_count_w < 32) begin : g_prepared_active_columns
    localparam int p_high_width = 32 - p_tile_count_w;
    logic [p_tile_count_w-1:0] distance_low;
    logic [p_high_width-1:0] high_i_a, high_i_b, high_i_target;
    logic high_i_carry, high_o_equal;
    logic high_equal, high_increment_equal;
    assign distance_low = i_reduction_len[p_tile_count_w-1:0] - descriptor_reduction[p_tile_count_w-1:0];
    assign high_i_carry = i_reduction_len[p_tile_count_w-1:0] < descriptor_reduction[p_tile_count_w-1:0];
    assign high_i_a = descriptor_reduction[31:p_tile_count_w];
    assign high_i_b = '0;
    assign high_i_target = i_reduction_len[31:p_tile_count_w];
    // 高位的两个完整比较同时准备，低位借位只选择已经完成的一位结果。
    conv_descriptor_match #(.p_width(p_high_width), .p_preserve_groups(1'b1)) u_distance_high_equal (
      .i_a(high_i_a), .i_b(high_i_target), .o_equal(high_equal)
    );
    conv_channel_increment_match #(.p_width(p_high_width)) u_distance_high_increment (
      .i_a(high_i_a), .i_target(high_i_target), .o_equal(high_increment_equal)
    );
`ifdef SYNTHESIS
    assign high_o_equal = high_i_carry ? high_increment_equal : high_equal;
`else
    logic high_reference_equal;
    add_equal #(.p_width(p_high_width)) u_distance_high_reference (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_i_carry), .o_equal(high_reference_equal)
    );
    always_comb begin
      high_o_equal = high_reference_equal;
      case (^{high_i_a, high_i_target, high_i_carry})
        1'b0, 1'b1: high_o_equal = high_i_carry ? high_increment_equal : high_equal;
        default: begin end
      endcase
    end
`endif
    assign prepared_active_columns = high_o_equal && distance_low < descriptor_columns ?
      distance_low : descriptor_columns;
  end else begin : g_prepared_active_columns_wide
    assign prepared_active_columns = i_reduction_len - descriptor_reduction < 32'(descriptor_columns) ?
      p_tile_count_w'(i_reduction_len - descriptor_reduction) : descriptor_columns;
  end
  conv_descriptor_group_steps u_group_steps (
    .i_reduction(descriptor_reduction), .i_group_channels(i_c.group_c),
    .o_next_group(prepared_next_group), .o_skip_group(prepared_skip_group)
  );
  // 准备项保存坐标起点与操作类型，提交时使用当前任务的步长。
  // 配置只在没有准备项时更新，因此步长在描述符接收至提交期间保持。
  always_comb begin
    prepared_coordinate_x = i_row_base_ix;
    prepared_coordinate_y = i_row_base_iy;
    if (o_incoming_next_position_fast) begin
      prepared_coordinate_x = window_next_ix;
      prepared_coordinate_y = window_next_iy;
    end
  end
  assign prepared_padding_value = {window_previous_padding, window_backward_padding,
    window_forward_padding, window_next_padding, i_next_row_padding, incoming_skip_padding,
    incoming_wrap_padding, incoming_step_padding, incoming_base_padding};
  // 各候选分别组合完整优先条件，末级独立归并，保持候选之间的并行关系。
  assign incoming_word_flags[9] = {4'd0, incoming_window_context, incoming_position_previous_row};
  assign incoming_word_flags[7] = {3'd0, incoming_window_context,
    incoming_position_previous_row, incoming_position_forward_tap};
  assign incoming_word_flags[8] = {2'd0, incoming_window_context, incoming_position_previous_row,
    incoming_position_forward_tap, incoming_position_backward_tap};
  assign incoming_word_flags[6] = {1'b0, incoming_window_context, incoming_position_previous_row,
    incoming_position_forward_tap, incoming_position_backward_tap, incoming_position_same_tap};
  assign incoming_word_flags[5] = {5'd0, o_incoming_next_tile_fast};
  assign incoming_word_flags[4] = {3'd0, o_incoming_next_tile_fast, o_incoming_skip_tap, i_kx0_q != 16'd0};
  assign incoming_word_flags[3] = incoming_word_flags[4];
  assign incoming_word_flags[2] = {2'd0, o_incoming_next_tile_fast,
    o_incoming_skip_tap, incoming_q_equal, i_incoming_tap_wrap};
  assign incoming_word_flags[1] = incoming_word_flags[2];
  assign incoming_word_flags[0] = {3'd0, o_incoming_next_tile_fast, o_incoming_skip_tap, incoming_q_equal};
  assign incoming_padding_flags[5] = {4'd0, incoming_window_context, incoming_position_same_tap};
  assign incoming_padding_flags[8] = {3'd0, incoming_window_context,
    incoming_position_same_tap, incoming_position_previous_row};
  assign incoming_padding_flags[6] = {2'd0, incoming_window_context, incoming_position_same_tap,
    incoming_position_previous_row, incoming_position_forward_tap};
  assign incoming_padding_flags[7] = {1'b0, incoming_window_context, incoming_position_same_tap,
    incoming_position_previous_row, incoming_position_forward_tap, incoming_position_backward_tap};
  assign incoming_padding_flags[4] = incoming_word_flags[5];
  assign incoming_padding_flags[3] = {4'd0, o_incoming_next_tile_fast, o_incoming_skip_tap};
  assign incoming_padding_flags[2:0] = incoming_word_flags[2:0];
  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_word_choice
    localparam int p_flags = candidate == 5 ? 1 : candidate == 9 ? 2 :
      candidate == 0 || candidate == 3 || candidate == 4 || candidate == 7 ? 3 : candidate == 6 ? 5 : 4;
    localparam logic [p_flags-1:0] p_expected = candidate == 0 || candidate == 2 || candidate == 5 ? p_flags'(1) :
      candidate == 1 ? p_flags'(0) : candidate == 3 ? p_flags'(2) : candidate == 4 || candidate == 9 ? p_flags'(3) :
      candidate == 6 ? p_flags'(17) : candidate == 7 ? p_flags'(5) : p_flags'(9);
    conv_descriptor_qualify #(.p_flags(p_flags), .p_expected(p_expected), .p_window_priority(candidate < 6)) u_choice (
      .i_flags(incoming_word_flags[candidate][p_flags-1:0]),
      .i_window({incoming_window_context, incoming_window_match}), .o_valid(incoming_word_choice[candidate])
    );
  end
  for (genvar candidate = 0; candidate < 9; candidate++) begin : g_padding_choice
    localparam int p_flags = candidate == 4 ? 1 : candidate == 3 || candidate == 5 ? 2 :
      candidate == 0 || candidate == 8 ? 3 : candidate == 7 ? 5 : 4;
    localparam logic [p_flags-1:0] p_expected = candidate == 0 || candidate == 2 || candidate == 3 || candidate == 4 ? p_flags'(1) :
      candidate == 1 ? p_flags'(0) : candidate == 5 ? p_flags'(3) : candidate == 6 ? p_flags'(9) :
      candidate == 7 ? p_flags'(17) : p_flags'(5);
    conv_descriptor_qualify #(.p_flags(p_flags), .p_expected(p_expected), .p_window_priority(candidate < 5)) u_choice (
      .i_flags(incoming_padding_flags[candidate][p_flags-1:0]),
      .i_window({incoming_window_context, incoming_window_match}), .o_valid(incoming_padding_choice[candidate])
    );
  end
  always_comb begin
    prepared_padding_select = '0;
    prepared_word_select = '0;
    if (o_incoming_next_position_fast) begin
      if (incoming_position_same_tap) prepared_padding_select[5] = 1'b1;
      else if (incoming_position_previous_row) prepared_padding_select[8] = 1'b1;
      else if (incoming_position_forward_tap) prepared_padding_select[6] = 1'b1;
      else prepared_padding_select[7] = 1'b1;
      if (incoming_position_previous_row) prepared_word_select[9] = 1'b1;
      else if (incoming_position_forward_tap) prepared_word_select[7] = 1'b1;
      else if (incoming_position_backward_tap) prepared_word_select[8] = 1'b1;
      else prepared_word_select[6] = 1'b1;
    end else if (o_incoming_next_tile_fast) begin
      prepared_padding_select[4] = 1'b1;
      prepared_word_select[5] = 1'b1;
    end else if (o_incoming_skip_tap) begin
      prepared_padding_select[3] = 1'b1;
      if (i_kx0_q != 16'd0) prepared_word_select[4] = 1'b1;
      else prepared_word_select[3] = 1'b1;
    end else if (!incoming_q_equal) begin
      if (i_incoming_tap_wrap) begin
        prepared_padding_select[2] = 1'b1;
        prepared_word_select[2] = 1'b1;
      end else begin
        prepared_padding_select[1] = 1'b1;
        prepared_word_select[1] = 1'b1;
      end
    end else begin
      prepared_padding_select[0] = 1'b1;
      prepared_word_select[0] = 1'b1;
    end
`ifdef SYNTHESIS
    prepared_word_select = incoming_word_choice;
    prepared_padding_select = incoming_padding_choice;
`endif
  end
  // 地址、坐标与像素先组成互斥候选，两级归约完成接收数据选择。
  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming_data
    logic [31:0] pixel_value;
    logic [31:0] kernel_x_value, kernel_y_value;
    logic [1:0][31:0] address_value;
    logic [p_coord_w-1:0] coordinate_x, coordinate_y;
    assign pixel_value = candidate == 0 ? i_row_base_pixel :
      candidate == 1 ? incoming_pixel_candidate[6] : candidate == 2 ? incoming_pixel_candidate[5] :
      candidate == 3 ? incoming_pixel_candidate[4] : candidate == 4 ? incoming_pixel_candidate[3] :
      candidate == 5 ? i_next_row_pixel : candidate == 6 ? window_next_pixel :
      candidate == 7 ? incoming_pixel_candidate[1] : candidate == 8 ? incoming_pixel_candidate[2] : incoming_pixel_candidate[0];
    assign address_value = candidate == 0 ? {i_row_group_base, i_row_base_addr} :
      candidate == 1 ? incoming_address_sum[0] : candidate == 2 ? incoming_address_sum[1] :
      candidate == 3 ? incoming_address_sum[2] : candidate == 4 ? incoming_address_sum[3] :
      candidate == 5 ? {i_next_row_group_base, i_next_row_addr} :
      candidate == 6 ? {window_next_group_base, window_next_addr} :
      candidate == 7 ? incoming_address_sum[4] : candidate == 8 ? incoming_address_sum[5] : incoming_address_sum[6];
    assign coordinate_x = candidate == 0 ? i_row_base_ix : candidate == 1 ? incoming_step_ix :
      candidate == 2 ? incoming_wrap_ix : candidate == 3 ? candidate_coordinate_sum[5] :
      candidate == 4 ? candidate_coordinate_sum[3] : candidate == 5 ? i_next_row_ix :
      candidate == 6 ? window_next_ix : candidate == 8 ? window_backward_ix : window_forward_ix;
    assign coordinate_y = candidate < 2 ? i_row_base_iy : candidate == 2 ? incoming_wrap_iy :
      candidate == 3 ? candidate_coordinate_sum[6] : candidate == 4 ? candidate_coordinate_sum[4] :
      candidate == 5 ? i_next_row_iy : candidate == 9 ? window_previous_iy : window_next_iy;
    assign incoming_data_candidate[candidate] = {coordinate_x, coordinate_y, pixel_value, address_value};
    assign incoming_tap_values[candidate] = candidate == 0 || candidate == 5 ? i_tap0 :
      candidate == 1 || candidate == 2 ? incoming_tap_candidate[4] :
      candidate == 3 || candidate == 4 ? incoming_tap_candidate[3] :
      candidate == 6 ? window_next_tap : candidate == 7 ? incoming_tap_candidate[1] :
      candidate == 8 ? incoming_tap_candidate[2] : incoming_tap_candidate[0];
    assign kernel_x_value = candidate == 0 || candidate == 5 ? i_kx0 :
      candidate == 1 ? i_kx0 + 32'd1 : candidate == 2 ? 32'd0 : candidate == 3 ? 32'd2 :
      candidate == 4 ? i_kx0 - 32'd1 : candidate == 6 ? {16'd0, window_next_kx} :
      candidate == 7 ? {16'd0, window_next_kx} + 32'd1 :
      candidate == 8 ? {16'd0, window_next_kx} - 32'd1 : 32'd1;
    assign kernel_y_value = candidate == 2 || candidate == 4 ? i_ky0 + 32'd1 :
      candidate < 6 ? i_ky0 : candidate == 9 ? {16'd0, window_next_ky} - 32'd1 :
      {16'd0, window_next_ky};
    assign incoming_kernel_values[candidate] = {kernel_y_value, kernel_x_value};
    assign o_incoming_group_candidates[candidate] = address_value[1];
    assign o_incoming_kernel_x_candidates[candidate] = kernel_x_value[15:0];
    assign o_incoming_pixel_candidates[candidate] = pixel_value;
    assign o_incoming_address_candidates[candidate] = address_value[0];
    assign o_incoming_y_candidates[candidate] = coordinate_y;
  end
  // 核位置直接选择已经完成的候选，窗口资格只参与末级数据归并。
  onehot_mux #(.p_choices(10), .p_width(32)) u_incoming_tap (
    .i_select(prepared_word_select), .i_data(incoming_tap_values), .o_data(incoming_tap_selected)
  );
  onehot_mux #(.p_choices(10), .p_width(64)) u_incoming_kernel (
    .i_select(prepared_word_select), .i_data(incoming_kernel_values), .o_data(incoming_kernel_selected)
  );
  assign o_incoming_pixel_select = prepared_word_select;
  for (genvar pair = 0; pair < 5; pair++) begin : g_incoming_pair
    assign incoming_data_pair[pair] =
      (incoming_data_candidate[2*pair] & {p_incoming_data_width{prepared_word_select[2*pair]}}) |
      (incoming_data_candidate[2*pair+1] & {p_incoming_data_width{prepared_word_select[2*pair+1]}});
  end
  assign incoming_data_selected = incoming_data_pair[0] | incoming_data_pair[1] |
      incoming_data_pair[2] | incoming_data_pair[3] | incoming_data_pair[4];
  // 各填充候选完成范围判断后，由独立的分组选择模块归并。
  onehot_mux #(.p_choices(9), .p_width(1)) u_incoming_padding (
    .i_select(prepared_padding_select), .i_data(prepared_padding_value),
    .o_data(incoming_padding_selected)
  );
  // 核位置与像素保存完整起点，提交阶段由操作类型选择任务内固定步长。
  always_comb begin
    prepared_tap_base = i_tap0;
    prepared_kernel_x_base = 16'(i_kx0);
    prepared_kernel_y_base = 16'(i_ky0);
    prepared_pixel_base = i_row_base_pixel;
    if (o_incoming_next_position_fast) begin
      prepared_tap_base = window_next_tap;
      prepared_kernel_x_base = window_next_kx;
      prepared_kernel_y_base = window_next_ky;
      prepared_pixel_base = window_next_pixel;
    end else if (o_incoming_next_tile_fast) begin
      prepared_pixel_base = i_next_row_pixel;
    end
  end
  // 两个地址共用同一来源，操作类型决定提交时的地址增量。
  always_comb begin
    prepared_address = {i_row_group_base, i_row_base_addr};
    if (o_incoming_next_position_fast)
      prepared_address = {window_next_group_base, window_next_addr};
    else if (o_incoming_next_tile_fast)
      prepared_address = {i_next_row_group_base, i_next_row_addr};
  end
  // 提交算术读取完整准备字段，直连模式直接输出当拍准备结果。
  assign commit_i_prepared_tile_packed = prepared_tile_q;
  assign commit_i_preparing_tile_packed = preparing_tile;
  assign commit_i_c = i_c;
  assign commit_i_row_wrap_dx = i_row_wrap_dx;
  assign commit_i_tap_wrap_dx = i_tap_wrap_dx;
  assign commit_i_tap_wrap_pixels = i_tap_wrap_pixels;
  assign commit_i_tap_pair_dx = i_tap_pair_dx;
  assign commit_i_tap_pair_pixels = i_tap_pair_pixels;
  assign commit_i_tap_step_bytes = i_tap_step_bytes;
  assign commit_i_tap_wrap_bytes = i_tap_wrap_bytes;
  assign commit_i_tap_pair_bytes = i_tap_pair_bytes;
  assign commit_i_ix = i_ix;
  assign commit_i_iy = i_iy;
  assign commit_i_last_kernel_col_q = i_last_kernel_col_q;
  assign commit_i_active_columns = prepared_active_columns;
  assign commit_i_next_group = prepared_next_group;
  assign commit_i_skip_group = prepared_skip_group;
  assign committing_tile = prepared_tile_t'(commit_o_committing_tile_packed);
  assign committing_coordinate_valid = commit_o_coordinate_valid;
  conv_descriptor_commit #(
    .p_size(p_size), .p_slot_w(p_slot_w), .p_lanes(p_lanes),
    .p_line_bytes(p_line_bytes), .p_register_descriptor(p_register_descriptor),
    .p_coord_w(p_coord_w)
  ) u_commit (
    .i_prepared_tile_packed(commit_i_prepared_tile_packed),
    .i_preparing_tile_packed(commit_i_preparing_tile_packed),
    .i_c(commit_i_c),
    .i_row_wrap_dx(commit_i_row_wrap_dx),
    .i_tap_wrap_dx(commit_i_tap_wrap_dx),
    .i_tap_wrap_pixels(commit_i_tap_wrap_pixels),
    .i_tap_pair_dx(commit_i_tap_pair_dx),
    .i_tap_pair_pixels(commit_i_tap_pair_pixels),
    .i_tap_step_bytes(commit_i_tap_step_bytes),
    .i_tap_wrap_bytes(commit_i_tap_wrap_bytes),
    .i_tap_pair_bytes(commit_i_tap_pair_bytes),
    .i_ix(commit_i_ix),
    .i_iy(commit_i_iy),
    .i_last_kernel_col_q(commit_i_last_kernel_col_q),
    .i_active_columns(commit_i_active_columns),
    .i_next_group(commit_i_next_group),
    .i_skip_group(commit_i_skip_group),
    .o_committing_tile_packed(commit_o_committing_tile_packed),
    .o_coordinate_valid(commit_o_coordinate_valid)
  );

  always_comb begin
    preparing_tile = '0;
    preparing_tile.operation = prepared_word_select;
    preparing_tile.row_wrap = i_row_wrap;
    preparing_tile.padding_select = prepared_padding_select;
    preparing_tile.padding_value = prepared_padding_value;
    preparing_tile.word_address = i_descriptor_response_forward ?
      i_addr[31:p_word_shift] : i_word_addr[31:p_word_shift];
    preparing_tile.saved_word_valid = (i_descriptor_response_forward) ||
      (i_word_valid && i_word_addr[p_word_shift-1:0] == '0);
    preparing_tile.invalid = !channel_descriptor_valid;
    preparing_tile.fast = o_incoming_fast;
    preparing_tile.padding = p_register_descriptor ? 1'b0 : o_incoming_padding;
    preparing_tile.word_hit = i_incoming_word_hit;
    preparing_tile.position = i_tile_p0;
    preparing_tile.reduction = i_tile_q0;
    preparing_tile.group_index = i_tile_group;
    preparing_tile.rows = p_tile_count_w'(i_tile_rows);
    preparing_tile.columns = prepared_columns;
    preparing_tile.active_columns = p_register_descriptor ? '0 : prepared_active_columns;
    preparing_tile.slot = i_tile_slot;
    preparing_tile.narrow_output = i_tile_narrow;
    preparing_tile.next_group = p_register_descriptor ? '0 : prepared_next_group;
    preparing_tile.skip_group = p_register_descriptor ? '0 : prepared_skip_group;
    preparing_tile.geometry = i_pred_enabled && (p_cache_policy!=3 || !i_c.windowed) &&
      (i_tile_cols==0 || 32'(i_tile_cols)==p_size) && i_tile_p0[3:0]==0 && i_tile_q0[3:0]==0 && i_tile_group<i_groups_q;
    preparing_tile.tap = p_register_descriptor ? prepared_tap_base : incoming_tap;
    preparing_tile.channel = o_incoming_ch;
    preparing_tile.kernel_x = p_register_descriptor ? prepared_kernel_x_base : 16'(o_incoming_kx);
    preparing_tile.kernel_y = p_register_descriptor ? prepared_kernel_y_base : 16'(o_incoming_ky);
    preparing_tile.kernel_last = incoming_kx_last;
    preparing_tile.input_x = p_register_descriptor ? prepared_coordinate_x : o_incoming_ix;
    preparing_tile.input_y = p_register_descriptor ? prepared_coordinate_y : o_incoming_iy;
    preparing_tile.pixel = p_register_descriptor ? prepared_pixel_base : o_incoming_pixel;
    preparing_tile.address = p_register_descriptor ? prepared_address[0] : o_incoming_addr;
    preparing_tile.group_address = p_register_descriptor ? prepared_address[1] : incoming_group_base;
    preparing_tile.channel_range = o_incoming_next_position_fast ? window_next_channel_range : i_group_range_next[1];
    preparing_tile.output_position_update = o_incoming_next_position_fast || o_incoming_next_tile_fast;
    preparing_tile.output_x = o_incoming_next_position_fast ? o_window_next_x : i_row_wrap ? 16'd0 : i_ox_q + 16'd1;
    preparing_tile.output_y = o_incoming_next_position_fast ? o_window_next_y : i_row_wrap ? i_oy_q + 16'd1 : i_oy_q;
    preparing_tile.output_wrap = o_incoming_next_position_fast ? window_next_last_col :
      i_row_wrap ? i_last_output_col_q == 16'd0 : i_row_next_o_equal;
  end
  assign tile_capture = i_tile_valid && i_tile_ready;
  // 当前分块释放状态时提交已准备描述符，保持原有接收与提交周期。
  assign o_tile_commit = p_register_descriptor ?
    (o_tile_prepared_valid && !i_error && (i_state[$clog2(IDLE)] || i_tile_finish)) : tile_capture;
  // 检查阶段读取已保存地址，描述符输入队列可以同时保存后续准备项。
  assign o_committing_saved_word_hit = descriptor_saved_word_valid_q && committing_saved_word_match;
  assign o_descriptor_padding = descriptor_padding_select_q ? descriptor_padding_value_q :
      !(&committing_coordinate_valid);
  // 两个数据字标签与运行地址并行比较，命中结果只控制检查阶段的状态。
  for (genvar target = 0; target < 2; target++) begin : g_commit_word_match
    localparam int p_tag_width = 32 - p_word_shift;
    localparam int p_group_count = (p_tag_width + 2) / 3;
    logic [p_tag_width-1:0] target_tag;
    (* keep = "true" *) logic [p_group_count-1:0] tag_group_equal;
    assign target_tag = target == 0 ? descriptor_word_address_q : i_word_addr[31:p_word_shift];
    for (genvar part = 0; part < p_group_count; part++) begin : g_group
      localparam int p_first = part * 3;
      localparam int p_width = p_tag_width - p_first < 3 ? p_tag_width - p_first : 3;
      assign tag_group_equal[part] =
          i_addr[p_word_shift + p_first +: p_width] == target_tag[p_first +: p_width];
    end
    if (target == 0) begin : g_saved_match
      assign committing_saved_word_match = &tag_group_equal;
    end else begin : g_live_match
      assign prepared_live_word_match = &tag_group_equal;
    end
  end
  // 当前数据字也可供下一描述符复用，标签和有效位均来自已经完成的返回。
  assign o_committing_live_word_hit = i_word_valid && prepared_live_word_match;
  //! 2. 保存窗口及描述符
  //! ---------------------

  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) window_next_valid <= 1'b0;
    else if (i_cfg_valid && i_cfg_ready) window_next_valid <= 1'b0;
    else if (window_prepare_write) window_next_valid <= next_position < i_position_count;
  end
  always_ff @(posedge i_clk) begin
    if (!i_rst_n) begin
    end else if (window_prepare_write) begin
      window_next_p <= next_position;
      window_next_q <= i_q0;
      window_next_tap <= i_tap0;
      o_window_next_ch <= i_ch0_q;
      o_window_group_remaining_q <= i_initial_group_remaining;
      window_next_kx <= i_kx0_q;
      window_forward_allowed_q <= i_kx0_q < i_last_kernel_col_q;
      window_backward_allowed_q <= i_kx0_q != 16'd0;
      window_previous_allowed_q <= i_c.kernel_w == 16'd3 && i_kx0_q == 16'd0 && i_ky0_q != 16'd0;
      window_next_ky <= i_ky0_q;
      o_window_next_x <= i_row_wrap ? 16'd0 : i_ox_q + 16'd1;
      o_window_next_y <= i_row_wrap ? i_oy_q + 16'd1 : i_oy_q;
      window_next_last_col <= i_row_wrap ? i_last_output_col_q==16'd0 : i_row_next_o_equal;
      window_next_ix <= i_next_row_ix;
      window_next_iy <= i_next_row_iy;
      window_next_pixel <= i_next_row_pixel;
      window_next_addr <= i_next_row_addr;
      window_next_group_base <= i_next_row_group_base;
      window_next_padding <= i_next_row_padding;
      window_next_channel_range <= i_group_range_next[1];
    end
  end

  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) o_tile_prepared_valid <= 1'b0;
    else if ((i_cfg_valid && i_cfg_ready) || i_error) o_tile_prepared_valid <= 1'b0;
    else if (p_register_descriptor && tile_capture) o_tile_prepared_valid <= 1'b1;
    else if (o_tile_commit) o_tile_prepared_valid <= 1'b0;
  end
  always_ff @(posedge i_clk) begin
    if (tile_capture) begin
      prepared_tile_q <= preparing_tile;
      // 命中数据随准备项保存，后续窗口更新缓存字不会改变该描述符的内容。
      prepared_word_data <= i_descriptor_response_forward ? i_cache_rsp_data : i_word_buf;
    end
  end

  // 提交时保存当前数据字与填充覆盖条件，下一准备项可继续写入输入队列。
  always_ff @(posedge i_clk) begin
    if (p_register_descriptor && o_tile_commit && !committing_tile.invalid && committing_tile.fast) begin
      o_descriptor_word_data_q <= prepared_word_data;
      descriptor_word_address_q <= prepared_tile_q.word_address;
      descriptor_saved_word_valid_q <= prepared_tile_q.saved_word_valid;
      descriptor_padding_select_q <= prepared_tile_q.padding_select[5];
      descriptor_padding_value_q <= prepared_tile_q.padding_value[5];
    end
  end

  //! 3. 输出接收资格
  //! -----------------

  assign channel_descriptor_valid = i_tile_rows != p_rw'(0) && 32'(i_tile_rows) <= p_size &&
    32'(i_tile_cols) <= p_size && o_tile_q_before_end && o_tile_rows_in_range;
  assign channel_accept_i_flags = {1'b1, o_incoming_fast, channel_descriptor_valid,
                                  i_tile_ready_context, !i_cfg_valid, i_tile_valid};
  assign o_channel_accept_fire = p_register_descriptor ?
    o_tile_commit && !committing_tile.invalid && committing_tile.fast : &channel_accept_i_flags;

endmodule
`default_nettype wire
