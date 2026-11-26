// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查卷积配置并准备坐标、通道、窗口回收和缓存索引参数。
// 共享乘法结果用于运行地址与预取地址计算，历史位置用于加速描述符解码。
module conv_im2col_geometry #(
  parameter int p_size=16,
  parameter int p_slot_w=3,
  parameter int p_lanes=2,
  parameter int p_line_bytes=16,
  parameter bit p_register_cache_request=1'b1,
  parameter bit p_register_descriptor=1'b1,
  parameter int p_cw=$clog2(p_size),
  localparam int p_lane_bytes=p_lanes <= 4 ? 4 : (1 << $clog2(p_lanes)),
  localparam int p_cache_read_bytes=p_lane_bytes < p_line_bytes ? p_lane_bytes : p_line_bytes,
  localparam int p_word_shift=$clog2(p_cache_read_bytes),
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_chunk_count_w=$clog2(p_lanes+1),
  localparam int p_saved_group_lanes=p_lanes <= 16 ? p_lane_bytes : 4,
  localparam int p_coord_w=35,
  localparam int p_prefetch_count_width=$clog2(p_line_bytes + 2),
  localparam int p_prepared_tile_width=528+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input wire logic i_clk, // 回绕状态寄存器的工作时钟。
  input wire logic i_rst_n, // 低有效异步复位。
  input wire logic i_cfg_valid, // 新卷积配置有效。
  input wire logic i_cfg_ready, // 新卷积配置可被接收。
  input wire conv_im2col_pkg::conv_cfg_t i_cfg, // 待接收的卷积配置。
  input wire conv_im2col_frontend_pkg::st_t i_state, // 当前运行状态。
  input wire conv_im2col_pkg::conv_cfg_t i_c, // 已保存的卷积配置。
  input wire logic [31:0] i_p0, // 分块起始输出位置。
  input wire logic [31:0] i_q0, // 分块起始归约位置。
  input wire logic [31:0] i_tap0, // 分块初始卷积核位置。
  input wire logic [15:0] i_ox_q, // 当前输出列坐标。
  input wire logic [15:0] i_oy_q, // 当前输出行坐标。
  input wire logic [15:0] i_ky_q, // 当前卷积核行坐标。
  input wire logic [15:0] i_kx_q, // 当前卷积核列坐标。
  input wire logic [15:0] i_ch_q, // 当前通道的十六位索引。
  input wire logic [15:0] i_kx0_q, // 分块初始卷积核列。
  input wire logic [15:0] i_ch0_q, // 分块的初始通道索引。
  input wire logic [31:0] i_ch, // 当前通道的扩展索引。
  input wire logic signed [p_coord_w-1:0] i_ix, // 当前输入列坐标。
  input wire logic signed [p_coord_w-1:0] i_iy, // 当前输入行坐标。
  input wire logic [31:0] i_pixel_index, // 当前输入像素的线性索引。
  input wire logic [3:0][31:0] i_coordinate_product_q, // 坐标生成阶段保存的四个乘积。
  input wire logic [1:0][32:0] i_coordinate_sum_q, // 坐标生成阶段保存的列、行加法结果。
  input wire logic [1:0] i_coordinate_borrow_q, // 坐标减去填充值时的列、行借位。
  input wire logic [31:0] i_channel_product, // 已保存的像素通道乘积。
  input wire logic [31:0] i_group_base_addr, // 当前输入像素的通道组起始地址。
  input wire logic [31:0] i_tap_group_base, // 当前卷积核位置的通道组地址。
  input wire logic [31:0] i_row_group_base, // 当前输出行起点的通道组地址。
  input wire logic [31:0] i_addr, // 当前请求的字节地址。
  input wire logic [p_chunk_count_w-1:0] i_chunk_count, // 当前输出传输包含的列数。
  input wire logic [p_lanes:0] i_chunk_selected, // 当前传输列数的并行选择位。
  input wire logic [31:0] i_decode_index, // 通用除法解码的当前计数。
  input wire logic [31:0] i_decode_outer, // 通用除法解码得到的商。
  input wire logic [31:0] i_decode_inner, // 通用除法解码得到的余数。
  input wire logic i_incoming_next_position_fast, // 输入描述符复用下一输出位置。
  input wire logic [15:0] i_window_next_ch, // 下一窗口位置的初始通道索引。
  input wire logic [15:0] i_request_y_q, // 已保存请求的输入行坐标。
  input wire logic [3:0] i_p_cache_valid, // 四个输出位置历史项的有效位。
  input wire logic i_last_p_valid, // 最近输出位置历史项有效。
  input wire logic [31:0] i_last_p, // 最近一次解码的输出位置。
  input wire logic i_last_p_overflow_q, // 最近输出位置的上界计算产生进位。
  input wire logic [15:0] i_last_y, // 历史输出位置的行坐标。
  input wire logic [15:0] i_last_x, // 历史输出位置的列坐标。
  input wire logic [31:0] i_incoming_pixel, // 已准备描述符的像素索引。
  input wire logic [3:0] i_prefetch_phase, // 预取地址生成的当前阶段。
  input wire logic [31:0] i_pf_address_term, // 预取地址生成需要累加的地址分量。
  input wire logic signed [p_coord_w-1:0] i_pfa_y, // 待计算预取位置的输入行坐标。
  input wire logic [31:0] i_pfa_channel, // 待计算预取位置的通道索引。
  input wire logic [31:0] i_pf0_x, // 预取第一阶段的输入列坐标。
  input wire logic [31:0] i_pf0_y, // 预取第一阶段的输入行坐标。
  input wire logic [31:0] i_pf1_pixel, // 预取第二阶段的线性像素索引。
  input wire logic [31:0] i_pf1_channel, // 预取第二阶段的通道索引。
  input wire logic signed [p_coord_w-1:0] i_request_y, // 当前请求的输入行坐标。
  input wire logic [1:0] i_address_step_phase, // 地址步长准备阶段。
  input wire logic signed [32:0] i_row_wrap_dx, // 输出位置换行的有符号输入列位移。
  input wire logic signed [32:0] i_tap_wrap_dx, // 卷积核换行的有符号输入列位移。
  input wire logic signed [32:0] i_row_wrap_pixels, // 输出位置换行的有符号像素位移。
  input wire logic signed [32:0] i_tap_wrap_pixels, // 卷积核换行的有符号像素位移。
  input wire logic [31:0] i_row_step_bytes, // 相邻输出位置沿列推进的字节数。
  input wire logic [31:0] i_tap_step_bytes, // 相邻卷积核位置沿列推进的字节数。
  input wire logic [31:0] i_row_wrap_bytes, // 输出位置换行的字节位移。
  input wire logic [31:0] i_tap_wrap_bytes, // 卷积核换行的字节位移。
  input wire logic signed [p_coord_w-1:0] i_row_base_ix, // 当前输出行起点的输入列坐标。
  input wire logic signed [p_coord_w-1:0] i_row_base_iy, // 当前输出行起点的输入行坐标。
  input wire logic [31:0] i_row_base_pixel, // 当前输出行起点的线性像素索引。
  input wire logic [31:0] i_row_base_addr, // 当前输出行起点的字节地址。
  input wire logic i_row_wrap_q, // 已保存的输出位置换行标志。
  input wire logic i_tap_wrap_q, // 已保存的卷积核换行标志。
  input wire logic [p_prepared_tile_width-1:0] i_committing_tile_packed, // 待接收分块的完整准备数据。
  input wire logic i_tile_commit, // 当前周期接收描述符。
  output logic o_cfg_ok, // 配置检查通过。
  output logic o_cfg_basic_valid, // 新配置的基本参数有效。
  output logic [2:0] o_cfg_prepare_phase, // 配置计算和检查阶段。
  output logic [63:0] o_cfg_input_bytes, // 计算得到的输入张量字节数。
  output logic [31:0] o_cfg_red, // 计算得到的归约长度。
  output logic [31:0] o_cfg_positions, // 计算得到的输出位置总数。
  output logic [15:0] o_last_group_channel_q, // 通道组内最后一个有效通道索引。
  output logic o_group_nonzero_q, // 配置中的每组通道数非零。
  output logic [31:0] o_channel_addr, // 当前输入位置的完整通道字节地址。
  output logic [31:0] o_next_row_group_base, // 下一输出行的通道组地址。
  output logic [2:0] o_decode_end_o_equal, // 三种除法解码对应的行末比较结果。
  output logic o_short_pixel_q, // 短像素模式下按窗口粒度缩放像素索引。
  output logic [15:0] o_retire_last_row_q, // 窗口回收判断使用的最后输出行索引。
  output logic [15:0] o_second_last_row_q, // 倒数第二个输出行索引。
  output logic [15:0] o_last_output_col_q, // 最后一个输出列索引。
  output logic [15:0] o_second_last_col_q, // 倒数第二个输出列索引。
  output logic [15:0] o_last_kernel_col_q, // 最后一个卷积核列索引。
  output logic o_kernel_width_valid_q, // 配置中的卷积核宽度非零。
  output logic o_history_limit_carry, // 历史位置上界低位运算产生进位。
  output logic o_p_fast_valid, // 输出位置快速解码结果有效。
  output logic o_p_fast_wrap, // 历史快速解码得到的输出换行标志。
  output logic [31:0] o_p_fast_y, // 历史快速解码得到的输出行坐标。
  output logic [31:0] o_p_fast_x, // 历史快速解码得到的输出列坐标。
  output logic [1:0] o_p_cache_select, // 需要保存的输出位置历史项。
  output logic [31:0] o_request_retire, // 当前请求对应的窗口回收位置。
  output logic [1:0][31:0] o_retirement_result, // 当前请求和预取请求的窗口回收位置。
  output logic o_window_index_valid_q, // 窗口索引满足缓存配置的使用条件。
  output logic [4:0] o_window_index_shift_q, // 窗口索引的右移位数。
  output logic [31:0] o_pf_step_base, // 预取跨度计算的最小像素步长。
  output logic [4:0] o_current_q_div3, // 当前归约位置除以三的商。
  output logic [15:0] o_current_q_remainder, // 当前归约位置除以三的余数。
  output logic [31:0] o_incoming_req_index, // 描述符来源的完整窗口索引。
  output logic [31:0] o_incoming_req_epoch, // 输入描述符对应的缓存纪元。
  output logic [4:0][31:0] o_epoch_o_sum, // 不同请求来源的通道偏移累加结果。
  output logic [31:0] o_stream_channel_full, // 流式推进后的完整通道索引。
  output logic [p_coord_w-1:0] o_bound_sum [7], // 七种候选坐标的边界计算结果。
  output logic [6:0] o_bound_valid, // 七种候选坐标对应的范围有效位。
  output logic [2:0] o_skip_bound_valid, // 跨分组位置对应的范围有效位。
  output logic [2:0] o_window_padding, // 三个窗口位置对应的填充标志。
  output logic o_next_word_o_equal, // 下一读取位置到达缓存字边界。
  output logic signed [p_coord_w-1:0] o_tap_pair_dx, // 相邻核位置对的有符号输入列位移。
  output logic [31:0] o_tap_pair_pixels, // 相邻核位置对的像素位移。
  output logic [31:0] o_tap_pair_bytes, // 相邻核位置对的字节位移。
  output logic o_row_wrap, // 输出位置沿列推进时换行。
  output logic o_tap_wrap, // 卷积核位置沿列推进时换行。
  output logic o_next_row_padding, // 下一输出行起点使用填充值。
  output logic o_next_tap_padding, // 下一卷积核位置使用填充值。
  output logic o_tap_next_o_equal, // 推进后的卷积核列到达最后一列。
  output logic o_row_next_o_equal, // 推进后的输出列到达最后一列。
  output logic signed [p_coord_w-1:0] o_next_row_ix, // 下一输出行起点的输入列坐标。
  output logic signed [p_coord_w-1:0] o_next_row_iy, // 下一输出行起点的输入行坐标。
  output logic signed [p_coord_w-1:0] o_next_tap_ix, // 下一卷积核位置的输入列坐标。
  output logic signed [p_coord_w-1:0] o_next_tap_iy, // 下一卷积核位置的输入行坐标。
  output logic [31:0] o_next_row_pixel, // 下一输出行起点的线性像素索引。
  output logic [31:0] o_next_tap_pixel, // 下一卷积核位置的线性像素索引。
  output logic [31:0] o_next_row_addr, // 下一输出行起点的字节地址。
  output logic [31:0] o_next_tap_addr, // 下一卷积核位置的输入地址。
  output logic o_cfg_output_last, // 初始输出列位于新配置的最后一列。
  output logic o_cfg_kernel_last, // 初始卷积核列位于新配置的最后一列。
  output logic o_cfg_incoming_kernel_last, // 描述符初始核列位于新配置的最后一列。
  output logic o_group_shape_o_valid, // 每组通道数支持位移解码。
  output logic o_kernel_shape_o_valid, // 卷积核宽度支持位移解码。
  output logic [4:0] o_group_width_shift, // 每组通道数对应的二进制位移量。
  output logic [4:0] o_kernel_width_shift, // 卷积核宽度对应的二进制位移量。
  output logic [5:0] o_k_decode_value, // 三列卷积核的行列解码结果。
  output logic [1:0][32:0] o_coordinate_product_sum, // 坐标乘积相加后的列、行结果。
  output logic [1:0][16:0] o_coordinate_low_difference, // 坐标低位减去填充值的结果和借位。
  output logic signed [p_coord_w-1:0] o_coordinate_padded_x, // 减去左侧填充量后的输入列坐标。
  output logic signed [p_coord_w-1:0] o_coordinate_padded_y, // 减去顶部填充量后的输入行坐标。
  output logic [31:0] o_group_address_sum, // 通道乘积加输入起始地址的结果。
  output logic [31:0] o_prefetch_address_sum, // 预取输入起始地址与通道乘积之和。
  output logic [31:0] o_prefetch_byte_offset, // 预取通道和像素形成的字节偏移。
  output logic [31:0] o_prefetch_pixel_sum, // 预取行乘积与列坐标之和。
  output logic [3:0][31:0] o_shared_coordinate_product, // 共享乘法器返回的四项坐标乘积。
  output logic [1:0][47:0] o_shared_channel_product // 共享乘法器返回的两项通道乘积。
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
  logic cfg_basic_saved;
  logic [31:0] cfg_input_hw;
  logic [31:0] cfg_kernel_taps;
  logic [31:0] cfg_position_product;
  logic [48:0] cfg_tensor_product;
  logic [47:0] cfg_reduction_product;
  logic cfg_address_overflow;
  logic [3:0] cfg_address_generate;
  logic [3:0] cfg_address_propagate;
  logic [16:0] channel_byte_offset;
  logic [2:0][31:0] decode_end_i_target;
  logic retire_enabled_q;
  logic [3:0] retire_shift_q;
  (* ram_style = "distributed" *) logic [63:0] p_cache_data [4];
  logic [63:0] p_cache_write_data;
  logic p_cache_write_enable;
  logic p_cache_hit;
  logic [15:0] p_cache_y;
  logic [15:0] p_cache_x;
  logic [31:0] p_decode;
  logic [15:0] p_delta;
  logic [15:0] p_wrap_target_q;
  logic [32:0] p_history_delta_q;
  logic [32:0] history_delta_full;
  logic history_range_valid;
  typedef struct packed {
    logic wrap, valid, row_advance;
    logic [16:0] column;
  } history_result_t;
  history_result_t history_result, history_result_q, selected_history;
  logic [16:0] history_limit_i_a;
  logic [16:0] history_limit_i_b;
  logic history_limit_o_less;
  logic unused_history_limit_equal;
  logic [15:0] history_carry_i_a, history_carry_i_b;
  logic unused_history_carry_equal;
  logic [16:0] p_sum_reduced;
  logic unused_p_sum_carry;
  logic unused_p_sum_reduced_carry;
  logic [16:0] p_sum;
  logic [15:0] p_sum_wrap_i_a;
  logic [15:0] p_sum_wrap_i_b;
  logic [15:0] p_sum_wrap_i_target;
  logic p_sum_wrap_i_carry_in;
  logic p_sum_wrap_o_equal;
  logic unused_p_sum_wrap_carry;
  logic [15:0] p_sum_last_i_a;
  logic [15:0] p_sum_last_i_b;
  logic [15:0] p_sum_last_i_target;
  logic p_sum_last_i_carry_in;
  logic p_sum_last_o_equal;
  logic [1:0][15:0] retirement_input;
  logic [31:0] cfg_pixel_bytes;
  logic [31:0] cfg_line_pixels;
  logic [p_prefetch_count_width-1:0] prefetch_line_pixels;
  logic [31:0] incoming_epoch_channel;
  logic [4:0][31:0] epoch_i_a;
  logic [4:0][31:0] epoch_i_b;
  logic epoch_i_carry;
  logic [4:0] unused_epoch_carry;
  logic [31:0] stream_epoch_xor;
  logic [31:0] stream_epoch_carry;
  logic [31:0] stream_channel_i_a;
  logic [31:0] stream_channel_i_b;
  logic unused_stream_channel_carry;
  logic [p_coord_w-1:0] bound_a [7];
  logic [p_coord_w-1:0] bound_b [7];
  logic [15:0] bound_limit [7];
  (* keep = 1 *) logic [6:0] bound_valid_reference;
  logic [31-p_word_shift:0] next_word_i_target;
  logic [1:0] next_word_match;
  logic [2:0][p_coord_w-1:0] tap_pair_i_a;
  logic [2:0][p_coord_w-1:0] tap_pair_i_b;
  logic [2:0][p_coord_w-1:0] tap_pair_o_sum;
  logic [15:0] tap_next_i_a;
  logic [15:0] tap_next_i_b;
  logic [15:0] tap_next_i_target;
  logic tap_next_i_carry_in;
  logic [15:0] row_next_i_a;
  logic [15:0] row_next_i_b;
  logic [15:0] row_next_i_target;
  logic row_next_i_carry_in;
  prepared_tile_t committing_tile;
  logic [31:0] channel_address_sum;
  logic [15:0] cfg_last_output_col;
  logic [15:0] cfg_last_kernel_col;
  logic unused_cfg_output_col_carry;
  logic unused_cfg_kernel_col_carry;
  logic [4:0][31:0] movement_i_a;
  logic [4:0][31:0] movement_i_b;
  logic [4:0][31:0] movement_step_delta, movement_wrap_delta;
  logic [4:0] movement_wrap_select;
  logic [4:0][31:0] movement_o_sum;
  logic [15:0] stride_shape_i_value;
  logic stride_shape_o_valid;
  logic [31:0] pixel_shape_i_value;
  logic pixel_shape_o_valid;
  logic [15:0] group_shape_i_value;
  logic group_shape_check_o_valid;
  logic [15:0] kernel_shape_i_value;
  logic kernel_shape_check_o_valid;
  logic [15:0] output_shape_i_value;
  logic output_shape_o_valid;
  logic output_shape_check_o_valid;
  logic [4:0] output_width_shift;
  logic [16:0] retire_bias_q;
  logic [30:0] retire_scaled_last;
  logic [16:0] retire_compare_delta;
  logic [15:0] retire_compare_q;
  logic retire_all_bounded_q;
  logic retire_no_bound_q;
  logic prefetch_retire_pfa_q;
  logic [17:0] history_reduce_i_a;
  logic [17:0] history_reduce_i_b;
  logic [17:0] history_reduce_o_sum;
  logic [17:0] history_reduce_generate;
  logic [18:0] history_reduce_full_sum;
  logic history_width_reached;
  logic [16:0] history_column_sum, history_column_reduced;
  logic history_column_advance;
  logic unused_history_reduce_high;
  logic unused_history_delta_carry;
  logic [16:0] history_next_y;
  logic unused_history_next_y_carry;
  (* keep = 1 *) logic [2:0] fast_position_source;
  logic [1:0][63:0] fast_position_pair, fast_position_pair_value;
  logic [63:0] fast_position_power, fast_position_cache;
  logic [63:0] fast_position_history, fast_position_next_row;
  logic [63:0] fast_position_data;
  logic [3:0] fast_wrap_source, fast_wrap_value;
  logic fast_wrap_selected;
  logic [5:0] q_decode_value;
  logic [3:0] q_decode_o_quotient;
  logic [1:0] q_decode_o_remainder;
  logic [31:0] group_channel_sum;
  logic [31:0] prefetch_channel_sum;
  logic [3:0][15:0] coordinate_a;
  logic [3:0][15:0] coordinate_b;
  logic [1:0][31:0] channel_a;
  logic [1:0][15:0] channel_b;
  logic [1:0][1:0][31:0] channel_partial;
  logic [1:0][31:0] channel_upper;
  (* keep = 1 *) logic cfg_group_within_input;
  (* keep = 1 *) logic [2:0] cfg_dimension_valid;
  logic cfg_s8_offset_valid;
  logic [p_line_bytes:0] cfg_line_threshold;
  logic [p_line_bytes:0] cfg_line_select;
  logic [31:0] cfg_base_step;
  assign committing_tile = prepared_tile_t'(i_committing_tile_packed);
  logic decode_position_equal;
  // 解码计数按三位分组比较，完成条件直接参与已有状态保存。
  conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_decode_position_match (
    .i_a(i_decode_index), .i_b(i_p0), .o_equal(decode_position_equal)
  );
  // 通道偏移保持十七位范围，完整字节地址使用一次定宽求和。

  always_ff @(posedge i_clk) begin
    if (i_state[$clog2(ADDRESS_BASE)])
      channel_byte_offset <= i_c.input_s16 ? {i_ch_q, 1'b0} : {1'b0, i_ch_q};
  end
  conv_full_address_add u_channel_address (
    .i_a(i_group_base_addr), .i_b({15'd0, channel_byte_offset}), .o_sum(channel_address_sum)
  );
  assign o_channel_addr = channel_address_sum;

  // 末列判断随坐标寄存，连续输出周期直接使用已保存的比较结果。

  assign {unused_cfg_output_col_carry, cfg_last_output_col} = {1'b0, i_cfg.output_w} - 17'd1;
  assign {unused_cfg_kernel_col_carry, cfg_last_kernel_col} = {1'b0, i_cfg.kernel_w} - 17'd1;
  assign o_cfg_output_last = i_ox_q == cfg_last_output_col;
  assign o_cfg_kernel_last = i_kx_q == cfg_last_kernel_col;
  assign o_cfg_incoming_kernel_last = i_kx0_q == cfg_last_kernel_col;

  // 列号加一后的末列关系直接检查进位一致性，与列号结果并行。
  assign tap_next_i_a = i_kx_q;
  assign tap_next_i_b = 16'd0;
  assign tap_next_i_target = o_last_kernel_col_q;
  assign tap_next_i_carry_in = 1'b1;
  add_equal #(.p_width(16)) u_tap_next (
    .i_a(tap_next_i_a), .i_b(tap_next_i_b), .i_target(tap_next_i_target),
    .i_carry_in(tap_next_i_carry_in), .o_equal(o_tap_next_o_equal)
  );
  assign row_next_i_a = i_ox_q;
  assign row_next_i_b = 16'd0;
  assign row_next_i_target = o_last_output_col_q;
  assign row_next_i_carry_in = 1'b1;
  add_equal #(.p_width(16)) u_row_next (
    .i_a(row_next_i_a), .i_b(row_next_i_b), .i_target(row_next_i_target),
    .i_carry_in(row_next_i_carry_in), .o_equal(o_row_next_o_equal)
  );

  // 高位是否为零直接检查逐位进位，低十六位独立完成图像范围比较。
  assign bound_a[0] = i_row_base_ix;
  assign bound_a[1] = i_row_base_iy;
  assign bound_a[2] = i_ix;
  assign bound_a[3] = i_iy;
  assign bound_b[0] = o_row_wrap ? p_coord_w'(i_row_wrap_dx) : p_coord_w'(i_c.stride_w);
  assign bound_b[1] = o_row_wrap ? p_coord_w'(i_c.stride_h) : '0;
  assign bound_b[2] = o_tap_wrap ? p_coord_w'(i_tap_wrap_dx) : p_coord_w'(i_c.dilation_w);
  assign bound_b[3] = o_tap_wrap ? p_coord_w'(i_c.dilation_h) : '0;
  assign bound_limit[0] = i_c.input_w;
  assign bound_limit[1] = i_c.input_h;
  assign bound_limit[2] = i_c.input_w;
  assign bound_limit[3] = i_c.input_h;
  assign bound_a[4] = i_row_base_ix;
  assign bound_a[5] = i_row_base_ix;
  assign bound_a[6] = i_row_base_iy;
  assign bound_b[4] = p_coord_w'(i_c.dilation_w);
  assign bound_b[5] = p_coord_w'(i_tap_wrap_dx);
  assign bound_b[6] = p_coord_w'(i_c.dilation_h);
  assign bound_limit[4] = i_c.input_w;
  assign bound_limit[5] = i_c.input_w;
  assign bound_limit[6] = i_c.input_h;
  for (genvar axis = 0; axis < 7; axis++) begin : g_coordinate_bound
    if (axis < 4 || !p_register_descriptor) begin : g_evaluate
      // 坐标和值和范围条件使用同一组输入，边界检查独立于完整进位传播。
      conv_coordinate_step #(.p_width(p_coord_w)) u_step (
        .i_base(bound_a[axis]), .i_delta(bound_b[axis]), .i_limit(bound_limit[axis]),
        .o_sum(o_bound_sum[axis]), .o_valid(bound_valid_reference[axis])
      );
    end else begin : g_prepared_coordinate
      assign o_bound_sum[axis] = '0;
      assign bound_valid_reference[axis] = 1'b0;
    end
  end

  // 固定步长对应的坐标区间在配置准备边沿保存，运行时分别比较高位和低十六位。
  if (!p_register_descriptor) begin : g_prepared_bounds
    logic [7:0][p_coord_w-1:0] range_delta, range_lower, range_upper;
    logic [7:0][p_coord_w-1:0] range_lower_q, range_upper_q;
    logic [7:0][15:0] range_limit;
    logic [7:0] range_cross, range_cross_q;
    logic [10:0] range_valid;
    logic row_y_valid, tap_y_valid;
    logic [6:0] prepared_valid;

    assign range_delta[0] = p_coord_w'(i_c.stride_w);
    assign range_delta[1] = p_coord_w'(i_row_wrap_dx);
    assign range_delta[2] = p_coord_w'(i_c.stride_h);
    assign range_delta[3] = p_coord_w'(i_c.dilation_w);
    assign range_delta[4] = p_coord_w'(i_tap_wrap_dx);
    assign range_delta[5] = p_coord_w'(i_c.dilation_h);
    assign range_delta[6] = o_tap_pair_dx;
    assign range_delta[7] = p_coord_w'(i_c.dilation_w) << 1;
    for (genvar range_index = 0; range_index < 8; range_index++) begin : g_range
      logic unused_lower_carry, unused_upper_carry;
      assign range_limit[range_index] = range_index == 2 || range_index == 5 ? i_c.input_h : i_c.input_w;
      parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(8), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_lower (
        .i_a(p_coord_w'(0)), .i_b(~range_delta[range_index]), .i_carry(1'b1),
        .o_sum(range_lower[range_index]), .o_carry(unused_lower_carry)
      );
      parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(8), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_upper (
        .i_a(p_coord_w'(range_limit[range_index])), .i_b(~range_delta[range_index]), .i_carry(1'b1),
        .o_sum(range_upper[range_index]), .o_carry(unused_upper_carry)
      );
      // 区间长度小于 2^16，端点第十六位的差异直接表示跨越低位分段。
      assign range_cross[range_index] = range_lower[range_index][16] ^ range_upper[range_index][16];
    end
    always_ff @(posedge i_clk) begin
      if (i_address_step_phase == 2'd3) begin
        range_lower_q <= range_lower;
        range_upper_q <= range_upper;
        range_cross_q <= range_cross;
      end
    end

    for (genvar candidate = 0; candidate < 11; candidate++) begin : g_lookup
      localparam int p_range_index = candidate < 6 ? candidate : candidate - 3;
      logic [p_coord_w-1:0] coordinate_base;
      assign coordinate_base = candidate == 2 || candidate == 8 ? i_row_base_iy :
          candidate == 3 || candidate == 4 ? i_ix : candidate == 5 ? i_iy : i_row_base_ix;
      conv_coordinate_range #(.p_width(p_coord_w)) u_range (
        .i_base(coordinate_base), .i_lower(range_lower_q[p_range_index]),
        .i_upper(range_upper_q[p_range_index]), .i_block_cross(range_cross_q[p_range_index]),
        .o_valid(range_valid[candidate])
      );
    end
    assign row_y_valid = !(|i_row_base_iy[p_coord_w-1:16]) && i_row_base_iy[15:0] < i_c.input_h;
    assign tap_y_valid = !(|i_iy[p_coord_w-1:16]) && i_iy[15:0] < i_c.input_h;
    assign prepared_valid[0] = o_row_wrap ? range_valid[1] : range_valid[0];
    assign prepared_valid[1] = o_row_wrap ? range_valid[2] : row_y_valid;
    assign prepared_valid[2] = o_tap_wrap ? range_valid[4] : range_valid[3];
    assign prepared_valid[3] = o_tap_wrap ? range_valid[5] : tap_y_valid;
    assign prepared_valid[6:4] = range_valid[8:6];
    assign o_skip_bound_valid = {row_y_valid, range_valid[10:9]};

    // 行步长端点已保存，窗口的前向、后向及前一核行端点继续完成固定偏移。
    logic [5:0][p_coord_w-1:0] window_lower_q, window_upper_q;
    logic [5:0] window_cross_q, window_valid;
    for (genvar step = 0; step < 6; step++) begin : g_window_range
      localparam int p_base_range = step < 4 ? step % 2 : 2;
      logic [p_coord_w-1:0] lower_base, upper_base, adjustment;
      logic [p_coord_w-1:0] lower_sum, upper_sum, coordinate_base;
      logic [15:0] coordinate_limit;
      logic block_cross;
      logic unused_lower_carry, unused_upper_carry;

      assign lower_base = step == 4 ? '0 : range_lower_q[p_base_range];
      assign upper_base = step == 4 ? p_coord_w'(i_c.input_h) : range_upper_q[p_base_range];
      assign adjustment = step < 2 ? ~p_coord_w'(i_c.dilation_w) :
          step < 4 ? p_coord_w'(i_c.dilation_w) : p_coord_w'(i_c.dilation_h);
      parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(8), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_lower (
        .i_a(lower_base), .i_b(adjustment), .i_carry(step < 2),
        .o_sum(lower_sum), .o_carry(unused_lower_carry)
      );
      parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(8), .p_preserve_groups(1'b1), .p_carry_select_width(16)) u_upper (
        .i_a(upper_base), .i_b(adjustment), .i_carry(step < 2),
        .o_sum(upper_sum), .o_carry(unused_upper_carry)
      );
      assign coordinate_limit = step < 4 ? i_c.input_w : i_c.input_h;
      assign block_cross = lower_sum[16] ^ upper_sum[16];
      always_ff @(posedge i_clk) begin
        if (i_address_step_phase == 2'd0) begin
          window_lower_q[step] <= lower_sum;
          window_upper_q[step] <= upper_sum;
          window_cross_q[step] <= block_cross;
        end
      end
      assign coordinate_base = step < 4 ? i_row_base_ix : i_row_base_iy;
      conv_coordinate_range #(.p_width(p_coord_w)) u_range (
        .i_base(coordinate_base), .i_lower(window_lower_q[step]),
        .i_upper(window_upper_q[step]), .i_block_cross(window_cross_q[step]),
        .o_valid(window_valid[step])
      );
`ifdef NPU_SIM_ASSERT
      logic [p_coord_w-1:0] reference_delta;
      assign reference_delta = (step == 4 ? p_coord_w'(0) : range_delta[p_base_range]) +
          (step < 2 ? p_coord_w'(i_c.dilation_w) : step < 4 ?
           -p_coord_w'(i_c.dilation_w) : -p_coord_w'(i_c.dilation_h));
      always @(posedge i_clk) begin
        if (i_rst_n && o_cfg_prepare_phase == 0 && i_address_step_phase == 0 &&
            !i_state[$clog2(IDLE)]) begin
          assert (window_lower_q[step] == -reference_delta);
          assert (window_upper_q[step] == p_coord_w'(coordinate_limit) - reference_delta);
        end
      end
`endif
    end
    assign o_window_padding[0] = !(o_row_wrap ? window_valid[1] : window_valid[0]) || !o_bound_valid[1];
    assign o_window_padding[1] = !(o_row_wrap ? window_valid[3] : window_valid[2]) || !o_bound_valid[1];
    assign o_window_padding[2] = !(o_row_wrap ? window_valid[1] : window_valid[0]) ||
        !(o_row_wrap ? window_valid[5] : window_valid[4]);
    for (genvar axis = 0; axis < 7; axis++) begin : g_result
`ifdef SYNTHESIS
      assign o_bound_valid[axis] = prepared_valid[axis];
`else
      always_comb begin
        case (^{bound_a[axis], bound_b[axis], bound_limit[axis]})
          1'b0, 1'b1: o_bound_valid[axis] = prepared_valid[axis];
          default: o_bound_valid[axis] = bound_valid_reference[axis];
        endcase
      end
`endif
    end
`ifdef NPU_SIM_ASSERT
    always @(posedge i_clk) begin
      if (i_rst_n && o_cfg_prepare_phase == 0 && i_address_step_phase == 0 &&
          !i_state[$clog2(IDLE)]) begin
        assert (o_bound_valid == bound_valid_reference);
        for (int range_index = 0; range_index < 8; range_index++) begin
          assert (range_lower_q[range_index] == -range_delta[range_index]);
          assert (range_upper_q[range_index] == p_coord_w'(range_limit[range_index]) - range_delta[range_index]);
        end
      end
    end
`endif
  end else begin : g_direct_bounds
    assign o_bound_valid = bound_valid_reference;
    assign o_skip_bound_valid = '0;
    assign o_window_padding = '0;
  end

  // 数据字匹配比较读取范围以外的高位，字内偏移单独提供进位。
  assign next_word_i_target = i_addr[31:p_word_shift];
  for (genvar wrap = 0; wrap < 2; wrap++) begin : g_next_word_match
    logic [31:0] byte_step;
    logic [p_word_shift:0] low_sum;
    assign byte_step = wrap == 0 ? i_tap_step_bytes : i_tap_wrap_bytes;
    assign low_sum = {1'b0, i_tap_group_base[p_word_shift-1:0]} +
        {1'b0, byte_step[p_word_shift-1:0]};
    (* keep_hierarchy = "yes" *)
    add_equal #(.p_width(32-p_word_shift), .p_preserve_bits(1'b1)) u_match (
      .i_a(i_tap_group_base[31:p_word_shift]), .i_b(byte_step[31:p_word_shift]),
      .i_target(next_word_i_target), .i_carry_in(low_sum[p_word_shift]),
      .o_equal(next_word_match[wrap])
    );
  end
`ifdef SYNTHESIS
  assign o_next_word_o_equal = o_tap_wrap ? next_word_match[1] : next_word_match[0];
`else
  always_comb begin
    case (^{i_tap_group_base, i_tap_step_bytes, i_tap_wrap_bytes, o_tap_wrap, i_addr})
      1'b0, 1'b1: o_next_word_o_equal = o_tap_wrap ? next_word_match[1] : next_word_match[0];
      default: o_next_word_o_equal = o_next_tap_addr[31:p_word_shift] == next_word_i_target;
    endcase
  end
`endif

  // 双核位置步长在配置准备期间保存，运行时只执行一次地址或坐标加法。
  assign tap_pair_i_a = {p_coord_w'(i_tap_wrap_bytes), p_coord_w'(32'(i_tap_wrap_pixels)), p_coord_w'(i_tap_wrap_dx)};
  assign tap_pair_i_b = {p_coord_w'(i_tap_step_bytes), p_coord_w'(i_c.dilation_w), p_coord_w'(i_c.dilation_w)};
  for (genvar source = 0; source < 3; source++) begin : g_tap_pair
    logic [p_coord_w-1:0] pair_sum;
    assign pair_sum = tap_pair_i_a[source] + tap_pair_i_b[source];
    assign tap_pair_o_sum[source] = pair_sum;
  end
  always_ff @(posedge i_clk) begin
    if (i_address_step_phase == 2'd2) o_tap_pair_dx <= $signed(tap_pair_o_sum[0]);
    if (i_address_step_phase == 2'd1) o_tap_pair_pixels <= tap_pair_o_sum[1][31:0];
    if (i_address_step_phase == 2'd0) o_tap_pair_bytes <= tap_pair_o_sum[2][31:0];
  end

  // 行、核位置和像素地址各自保留完整三十二位模加法结果。
  assign movement_i_a = {i_pixel_index, i_tap_group_base, i_row_base_pixel, i_row_group_base, i_row_base_addr};
  assign movement_i_b[0] = o_row_wrap ? i_row_wrap_bytes : i_row_step_bytes;
  assign movement_i_b[1] = movement_i_b[0];
  assign movement_i_b[2] = o_row_wrap ? 32'(i_row_wrap_pixels) : {16'd0, i_c.stride_w};
  assign movement_i_b[3] = o_tap_wrap ? i_tap_wrap_bytes : i_tap_step_bytes;
  assign movement_i_b[4] = o_tap_wrap ? 32'(i_tap_wrap_pixels) : {16'd0, i_c.dilation_w};
  assign movement_step_delta = {{16'd0, i_c.dilation_w}, i_tap_step_bytes,
      {16'd0, i_c.stride_w}, i_row_step_bytes, i_row_step_bytes};
  assign movement_wrap_delta = {32'(i_tap_wrap_pixels), i_tap_wrap_bytes,
      32'(i_row_wrap_pixels), i_row_wrap_bytes, i_row_wrap_bytes};
  assign movement_wrap_select = {{2{o_tap_wrap}}, {3{o_row_wrap}}};
  for (genvar source = 0; source < 5; source++) begin : g_movement_sum
    logic [31:0] movement_sum;
    // 行末和核末标志已由寄存器保存，每种地址共用一个完整加法器。
    conv_geometry_movement_add u_sum (
      .i_base(movement_i_a[source]), .i_delta(movement_i_b[source]),
      .o_sum(movement_sum)
    );
`ifdef SYNTHESIS
    assign movement_o_sum[source] = movement_sum;
`else
    always_comb begin
      case (^{movement_i_a[source], movement_step_delta[source], movement_wrap_delta[source],
              movement_wrap_select[source]})
        1'b0, 1'b1: movement_o_sum[source] = movement_sum;
        default: movement_o_sum[source] = movement_i_a[source] + movement_i_b[source];
      endcase
    end
`endif
  end

  // 配置阶段保存乘积，输出传输期间的行边界和核边界只执行加法与范围判断。
  assign o_row_wrap = i_row_wrap_q;
  assign o_tap_wrap = i_tap_wrap_q;
  always_comb begin
    o_next_row_ix = $signed(o_bound_sum[0]);
    o_next_row_iy = $signed(o_bound_sum[1]);
    o_next_row_pixel=movement_o_sum[2];
    o_next_row_addr=movement_o_sum[0];
    o_next_row_group_base=movement_o_sum[1];
    // 有效图像坐标的高位必须全为零，低十六位再与图像尺寸比较。
    o_next_row_padding = !o_bound_valid[0] || !o_bound_valid[1];
    // 配置阶段保存卷积核末列，当前列判断不再经过加一进位。
    o_next_tap_ix = $signed(o_bound_sum[2]);
    o_next_tap_iy = $signed(o_bound_sum[3]);
    o_next_tap_pixel=movement_o_sum[4];
    o_next_tap_addr=movement_o_sum[3];
    o_next_tap_padding = !o_bound_valid[2] || !o_bound_valid[3];
  end

  // 配置和分块解码共用分组幂次检查，组合结果由原有控制周期接收。

  assign stride_shape_i_value = i_cfg.stride_h;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_stride_shape (
    .i_value(stride_shape_i_value),
    .o_valid(stride_shape_o_valid)
  );

  assign pixel_shape_i_value = cfg_pixel_bytes;
  onehot_check #(.p_width(32), .p_allow_zero(1'b0)) u_pixel_shape (
    .i_value(pixel_shape_i_value),
    .o_valid(pixel_shape_o_valid)
  );

  assign group_shape_i_value = i_cfg.group_c;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_group_shape (
    .i_value(group_shape_i_value),
    .o_valid(group_shape_check_o_valid)
  );

  assign kernel_shape_i_value = i_cfg.kernel_w;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_kernel_shape (
    .i_value(kernel_shape_i_value),
    .o_valid(kernel_shape_check_o_valid)
  );

  assign output_shape_i_value = i_cfg.output_w;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_output_shape (
    .i_value(output_shape_i_value),
    .o_valid(output_shape_check_o_valid)
  );
  // 形状、移位量和连续通道条件随配置保存，运行阶段直接读取寄存结果。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_group_shape_o_valid <= 1'b0;
      o_kernel_shape_o_valid <= 1'b0;
      output_shape_o_valid <= 1'b0;
      output_width_shift <= 5'd0;
      o_group_width_shift <= 5'd0;
      o_kernel_width_shift <= 5'd0;
    end else if (i_cfg_valid && i_cfg_ready) begin
      o_group_shape_o_valid <= group_shape_check_o_valid;
      o_kernel_shape_o_valid <= kernel_shape_check_o_valid;
      output_shape_o_valid <= output_shape_check_o_valid;
      output_width_shift <= power_shift({16'd0,i_cfg.output_w});
      o_group_width_shift <= power_shift({16'd0,i_cfg.group_c});
      o_kernel_width_shift <= power_shift({16'd0,i_cfg.kernel_w});
    end
  end
  function automatic logic [4:0] power_shift(input logic [31:0] value);
    logic [4:0] result;
    result=0;
    for (int b=0;b<32;b++) if (value[b]) result=5'(b);
    return result;
  endfunction
  // 配置准备阶段保存行偏移和限幅阈值，运行时的加法与范围判断并行。

  assign retire_scaled_last = {15'd0, o_retire_last_row_q} << retire_shift_q;
  assign retire_compare_delta = {1'b0, retire_compare_q} - {1'b0, i_c.pad_top};
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      retire_bias_q <= 17'd0;
      retire_compare_q <= 16'd0;
      retire_all_bounded_q <= 1'b0;
      retire_no_bound_q <= 1'b0;
    end else begin
      if (o_cfg_prepare_phase == 3'd1) begin
        retire_bias_q <= {1'b0, i_c.pad_top} +
          (o_short_pixel_q ? (17'd1 << retire_shift_q) : 17'd0);
        // 准备期间复用最终阈值寄存器，先保存低位及高位范围分类。
        retire_compare_q <= retire_scaled_last[15:0];
        retire_all_bounded_q <= !(|retire_scaled_last[30:16]);
        retire_no_bound_q <= |retire_scaled_last[30:17];
      end
      if (o_cfg_prepare_phase == 3'd2) begin
        retire_compare_q <= retire_compare_delta[15:0];
        retire_all_bounded_q <= retire_all_bounded_q && retire_compare_delta[16];
        retire_no_bound_q <= retire_no_bound_q ||
          (!retire_all_bounded_q && !retire_compare_delta[16]);
      end
    end
  end

  // 预取输入选择随原状态转换保存，计算端口直接使用已寄存的一位选择。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) prefetch_retire_pfa_q <= 1'b0;
    else if (i_cfg_valid && i_cfg_ready) prefetch_retire_pfa_q <= 1'b0;
    else prefetch_retire_pfa_q <= i_prefetch_phase == 4'd3;
  end

  // 请求和预取各共用一个计算端口，全部结果仍在原请求接收周期使用。
  assign retirement_input[0] = p_register_cache_request ?
      i_request_y_q : i_request_y[15:0];
  assign retirement_input[1] = prefetch_retire_pfa_q ? i_pfa_y[15:0] : i_pf0_y[15:0];
  for (genvar row_port = 0; row_port < 2; row_port++) begin : g_retirement_port
    logic [17:0] biased_row, retire_payload_row;
    logic [3:0] retire_payload_shift;
    logic limit_reached;

    logic unused_row_carry;

    logic [17:0] retire_i_a, retire_i_b;
    logic retire_i_carry;
    assign retire_i_a = {2'b0, retirement_input[row_port]};
    assign retire_i_b = {1'b0, retire_bias_q};
    assign retire_i_carry = 1'b0;
    // 行偏移先完成定宽求和，移位使用缓存的接收寄存级。
    parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1)) u_row_bias (
      .i_a(retire_i_a), .i_b(retire_i_b), .i_carry(retire_i_carry),
      .o_sum(biased_row), .o_carry(unused_row_carry)
    );
    assign limit_reached = retire_all_bounded_q ||
      (!retire_no_bound_q && retirement_input[row_port] >= retire_compare_q);
    assign retire_payload_row = limit_reached ? {2'b0, o_retire_last_row_q} : biased_row;
    assign retire_payload_shift = limit_reached ? 4'd0 : retire_shift_q;
    // 元数据低十八位保存被移位数，随后四位保存移位量，第22位表示禁止释放。
    // 缓存接收寄存之后执行移位，高九位保留为零。
    assign o_retirement_result[row_port] =
        {9'd0, !retire_enabled_q, retire_payload_shift, retire_payload_row};
  end
  assign o_request_retire = o_retirement_result[0];

  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。
  // 解码行尾在减去输出宽度之前检查模加法等式，与坐标结果并行。
  assign p_decode = i_p0;
  assign o_p_cache_select = 2'(p_decode >> p_cw);
  if (p_register_cache_request) begin : g_saved_position_lookup
    logic [1:0] lookup_index;
    logic [63:0] lookup_data;
    logic lookup_hit;
    logic hit_q;
    logic [31:0] coordinates_q;

    // 描述符提交时读取历史项，命中判断和坐标在执行解码前共同保存。
    assign lookup_index = 2'(committing_tile.position >> p_cw);
    assign lookup_data = p_cache_data[lookup_index];
    logic lookup_tag_equal;
    // 历史项标签按三位同时比较，命中只归并保存的组结果。
    conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_history_tag (
      .i_a(lookup_data[63:32]), .i_b(committing_tile.position), .o_equal(lookup_tag_equal)
    );
    assign lookup_hit = i_p_cache_valid[lookup_index] && lookup_tag_equal;
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) hit_q <= 1'b0;
      else if (i_cfg_valid && i_cfg_ready) hit_q <= 1'b0;
      else if (i_tile_commit && !committing_tile.invalid) hit_q <= lookup_hit;
      else if (p_cache_write_enable) hit_q <= 1'b1;
    end
    // 当前坐标写入历史表时，同一项的保存结果同步更新。
    always_ff @(posedge i_clk) begin
      if (i_tile_commit && !committing_tile.invalid) coordinates_q <= lookup_data[31:0];
      else if (p_cache_write_enable) coordinates_q <= p_cache_write_data[31:0];
    end
    assign p_cache_hit = hit_q;
    assign {p_cache_y, p_cache_x} = coordinates_q;
`ifdef NPU_SIM_ASSERT
    always @(posedge i_clk) begin
      if (i_rst_n) begin
        assert (!(i_tile_commit && !committing_tile.invalid && p_cache_write_enable));
        if (i_state[$clog2(P_DECODE)]) begin
          assert (hit_q == (i_p_cache_valid[o_p_cache_select] &&
              p_cache_data[o_p_cache_select][63:32] == i_p0));
          if (hit_q) assert (coordinates_q == p_cache_data[o_p_cache_select][31:0]);
        end
      end
    end
`endif
  end else begin : g_current_position_lookup
    logic [31:0] lookup_key;
    assign {lookup_key, p_cache_y, p_cache_x} = p_cache_data[o_p_cache_select];
    logic lookup_tag_equal;
    conv_descriptor_match #(.p_width(32), .p_preserve_groups(1'b1)) u_history_tag (
      .i_a(lookup_key), .i_b(p_decode), .o_equal(lookup_tag_equal)
    );
    assign p_cache_hit = i_p_cache_valid[o_p_cache_select] && lookup_tag_equal;
  end
  assign p_cache_write_enable = i_rst_n &&
      ((i_state[$clog2(P_DECODE)] && o_p_fast_valid) ||
       (i_state[$clog2(P_WAIT)] && decode_position_equal));
  assign p_cache_write_data = i_state[$clog2(P_DECODE)] ?
      {i_p0, 16'(o_p_fast_y), 16'(o_p_fast_x)} : {i_p0, 16'(i_decode_outer), 16'(i_decode_inner)};
  // 只有解码成功才更新有效项，未使用的数据不需要复位写端口。
  always_ff @(posedge i_clk) begin
    if (p_cache_write_enable) p_cache_data[o_p_cache_select] <= p_cache_write_data;
  end

  // 三个解码范围的末项检查并行进行，控制结果不等待计数器加一。
  assign decode_end_i_target[0] = {16'd0, i_c.output_w};
  assign decode_end_i_target[1] = {16'd0, i_c.group_c};
  assign decode_end_i_target[2] = {16'd0, i_c.kernel_w};
  for (genvar decode_dimension = 0; decode_dimension < 3; decode_dimension++) begin : g_decode_end
    logic [31:0] end_i_a, end_i_b, end_i_target;
    logic end_i_carry_in;
    logic end_o_equal;

    assign end_i_a = i_decode_inner;
    assign end_i_b = '0;
    assign end_i_target = decode_end_i_target[decode_dimension];
    assign end_i_carry_in = 1'b1;
    assign o_decode_end_o_equal[decode_dimension] = end_o_equal;
    add_equal #(.p_width(32)) u_end (
      .i_a(end_i_a), .i_b(end_i_b), .i_target(end_i_target),
      .i_carry_in(end_i_carry_in), .o_equal(end_o_equal)
    );
  end
  // 接收位置与历史位置的差值采用并行分段算术，并在坐标解码前保存。
  // 位置差在描述符提交时保存；历史位置更新为当前位置时，差值同时归零。
  parallel_prefix_add #(.p_width(33), .p_group_width(4), .p_preserve_groups(1'b1),
        .p_dsp_split_width(17), .p_parallel_high_prefix(1'b1),
        .p_keep_carry(1'b0), .p_preserve_grouped_unknowns(1'b1),
        .p_direct_subtract(1'b1)) u_history_delta (
    .i_a({1'b0, committing_tile.position}), .i_b(~{1'b0, i_last_p}), .i_carry(1'b1),
    .o_sum(history_delta_full), .o_carry(unused_history_delta_carry)
  );
  assign history_carry_i_a = ~i_c.output_w;
  assign history_carry_i_b = i_p0[15:0];
  unsigned_compare #(.p_width(16)) u_history_carry (
    .i_a(history_carry_i_a), .i_b(history_carry_i_b),
    .o_less(o_history_limit_carry), .o_equal(unused_history_carry_equal)
  );
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) p_history_delta_q <= 33'd0;
    else if (i_tile_commit && !committing_tile.invalid) p_history_delta_q <= history_delta_full;
    else if (p_cache_write_enable) p_history_delta_q <= 33'd0;
  end
  // 完整差值同时覆盖前向范围与借位，行末溢出位保留三十二位位置语义。
  assign history_limit_i_a = {1'b0, i_c.output_w};
  assign history_limit_i_b = p_history_delta_q[16:0];
  unsigned_compare #(.p_width(17)) u_history_limit (
    .i_a(history_limit_i_a), .i_b(history_limit_i_b),
    .o_less(history_limit_o_less), .o_equal(unused_history_limit_equal)
  );
  assign history_range_valid = i_last_p_valid && !i_last_p_overflow_q &&
      !(|p_history_delta_q[32:17]) && !history_limit_o_less;
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) p_wrap_target_q <= 16'd0;
    else if (i_cfg_valid && i_cfg_ready) p_wrap_target_q <= {i_cfg.output_w[14:0], 1'b0} - 16'd1;
  end
  // 位置与位置差在同一个提交事件保存，历史位置更新时差值同时归零。
  assign p_delta = p_history_delta_q[15:0];
  parallel_prefix_add #(.p_width(17), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(8)) u_history_sum (
    .i_a({1'b0, i_last_x}), .i_b({1'b0, p_delta}), .i_carry(1'b0),
    .o_sum(p_sum), .o_carry(unused_p_sum_carry)
  );

  // 历史列、位置增量和输出宽度先压缩，减法不再依赖前一级完整和值。
  assign history_reduce_i_a = {2'b0, i_last_x} ^ {2'b0, p_delta} ^ ~{2'b0, i_c.output_w};
  assign history_reduce_generate = ({2'b0, i_last_x} & {2'b0, p_delta}) |
    (({2'b0, i_last_x} | {2'b0, p_delta}) & ~{2'b0, i_c.output_w});
  assign {unused_history_reduce_high, history_reduce_i_b} = {history_reduce_generate, 1'b1};
  parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(8)) u_history_reduce (
    .i_a(history_reduce_i_a), .i_b(history_reduce_i_b), .i_carry(1'b0),
    .o_sum(history_reduce_full_sum[17:0]), .o_carry(history_reduce_full_sum[18])
  );
  assign {unused_p_sum_reduced_carry, history_reduce_o_sum} = history_reduce_full_sum;
  assign p_sum_reduced = history_reduce_o_sum[16:0];
  assign history_width_reached = !history_reduce_o_sum[17];

  // 历史起点持续准备，接收位置在原描述符边沿形成列与换行候选。
  if (!p_register_descriptor) begin : g_history_columns
    logic [17:0] origin_value, limit_value, origin_q, limit_q;
    logic [17:0] limit_xor, limit_generate;
    logic [16:0] column_sum, column_sum_q;
    logic [17:0] column_reduced, column_reduced_q;
    logic position_borrow;
    logic unused_origin_carry, unused_limit_carry;
    logic unused_sum_carry, unused_reduced_carry;

    parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(9)) u_origin (
      .i_a({2'b0, i_last_p[15:0]}), .i_b(~{2'b0, i_last_x}), .i_carry(1'b1),
      .o_sum(origin_value), .o_carry(unused_origin_carry)
    );
    assign limit_xor = {2'b0, i_last_p[15:0]} ^ ~{2'b0, i_last_x} ^ {2'b0, i_c.output_w};
    assign limit_generate = ({2'b0, i_last_p[15:0]} & ~{2'b0, i_last_x}) |
      (({2'b0, i_last_p[15:0]} | ~{2'b0, i_last_x}) & {2'b0, i_c.output_w});
    parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(9)) u_limit (
      .i_a(limit_xor), .i_b({limit_generate[16:0], 1'b0}), .i_carry(1'b1),
      .o_sum(limit_value), .o_carry(unused_limit_carry)
    );
    always_ff @(posedge i_clk) begin
      origin_q <= origin_value;
      limit_q <= limit_value;
    end
    assign position_borrow = committing_tile.position[15:0] < i_last_p[15:0];
    parallel_prefix_add #(.p_width(17), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(9)) u_column (
      .i_a({1'b0, committing_tile.position[15:0]}), .i_b(~origin_q[16:0]), .i_carry(1'b1),
      .o_sum(column_sum), .o_carry(unused_sum_carry)
    );
    parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1), .p_carry_select_width(9)) u_reduced (
      .i_a({2'b0, committing_tile.position[15:0]}), .i_b(~limit_q), .i_carry(1'b1),
      .o_sum(column_reduced), .o_carry(unused_reduced_carry)
    );
    // 位置差按十六位取模，借位修正仅影响候选的第十六位及其进位。
    always_ff @(posedge i_clk) begin
      column_sum_q <= {column_sum[16] ^ position_borrow, column_sum[15:0]};
      column_reduced_q <= {column_reduced[17:16] + 2'(position_borrow), column_reduced[15:0]};
    end
`ifdef SYNTHESIS
    assign history_column_sum = column_sum_q;
    assign history_column_reduced = column_reduced_q[16:0];
    assign history_column_advance = !column_reduced_q[17];
`else
    // 未知的历史字段使用原定宽表达式传播，已知字段使用准备结果。
    always_comb begin
      case (^{i_last_x, p_history_delta_q, i_c.output_w})
        1'b0, 1'b1: begin
          history_column_sum = column_sum_q;
          history_column_reduced = column_reduced_q[16:0];
          history_column_advance = !column_reduced_q[17];
        end
        default: begin
          history_column_sum = p_sum;
          history_column_reduced = p_sum_reduced;
          history_column_advance = history_width_reached;
        end
      endcase
    end
`endif
`ifdef NPU_SIM_ASSERT
    always @(posedge i_clk) begin
      if (i_rst_n && i_tile_commit && !committing_tile.invalid) begin
        assert (origin_q == {2'b0, i_last_p[15:0]} - {2'b0, i_last_x});
        assert (limit_q == {2'b0, i_last_p[15:0]} - {2'b0, i_last_x} + {2'b0, i_c.output_w});
      end
      if (i_rst_n && i_state[$clog2(P_DECODE)]) begin
        assert (column_sum_q == p_sum);
        assert (column_reduced_q[16:0] == p_sum_reduced);
        assert (!column_reduced_q[17] == history_width_reached);
      end
    end
`endif
  end else begin : g_history_columns_direct
    assign history_column_sum = p_sum;
    assign history_column_reduced = p_sum_reduced;
    assign history_column_advance = history_width_reached;
  end

  // 已保存的位置差与历史列数直接组成行尾等式，逐位比较和坐标求和并行。
  assign p_sum_wrap_i_a = i_last_x;
  logic history_last_after, history_wrap_after, history_wrap_selected;
  logic unused_history_last_equal, unused_history_wrap_equal;
  assign p_sum_wrap_i_b = p_history_delta_q[15:0];
  assign unused_p_sum_wrap_carry = 1'b0;
  assign p_sum_wrap_i_target = p_wrap_target_q;
  assign p_sum_wrap_i_carry_in = 1'b0;
  (* keep_hierarchy = "yes" *) add_equal #(.p_width(16), .p_preserve_bits(1'b1)) u_p_sum_wrap (
    .i_a(p_sum_wrap_i_a),
    .i_b(p_sum_wrap_i_b),
    .i_target(p_sum_wrap_i_target),
    .i_carry_in(p_sum_wrap_i_carry_in),
    .o_equal(p_sum_wrap_o_equal)
  );
  assign p_sum_last_i_a = p_sum_wrap_i_a;
  assign p_sum_last_i_b = p_sum_wrap_i_b;
  assign p_sum_last_i_target = o_last_output_col_q;
  assign p_sum_last_i_carry_in = 1'b0;
  (* keep_hierarchy = "yes" *) add_equal #(.p_width(16), .p_preserve_bits(1'b1)) u_p_sum_last (
    .i_a(p_sum_last_i_a), .i_b(p_sum_last_i_b), .i_target(p_sum_last_i_target),
    .i_carry_in(p_sum_last_i_carry_in), .o_equal(p_sum_last_o_equal)
  );
  // 两个边界独立比较，行末表达式只读取已经归并的一位结果。
  parallel_unsigned_compare #(.p_width(16)) u_history_last_order (
    .i_a(p_sum_last_i_target), .i_b(i_last_x),
    .o_less(history_last_after), .o_equal(unused_history_last_equal)
  );
  parallel_unsigned_compare #(.p_width(16)) u_history_wrap_order (
    .i_a(p_sum_wrap_i_target), .i_b(i_last_x),
    .o_less(history_wrap_after), .o_equal(unused_history_wrap_equal)
  );
  conv_history_wrap_select u_history_wrap (
    .i_width_nonzero(i_c.output_w != 16'd0), .i_sum_last_equal(p_sum_last_o_equal),
    .i_last_after(history_last_after), .i_sum_wrap_equal(p_sum_wrap_o_equal),
    .i_last_col_high(o_last_output_col_q[15]), .i_wrap_after(history_wrap_after),
    .o_wrap(history_wrap_selected)
  );
  always_comb begin
    history_result.valid = history_range_valid;
    history_result.row_advance = history_column_advance;
    history_result.column = history_column_advance ? history_column_reduced : history_column_sum;
    history_result.wrap = history_wrap_selected;
  end
  if (p_register_descriptor) begin : g_history_prepare
    always_ff @(posedge i_clk) begin
      if (i_state[$clog2(P_HISTORY)]) history_result_q <= history_result;
    end
    assign selected_history = history_result_q;
  end else begin : g_history_direct
    assign history_result_q = '0;
    assign selected_history = history_result;
  end
  // 相邻行坐标独立求和，行边界结果只控制末端选择。
  conv_history_row_increment u_history_next_y (
    .i_row(i_last_y), .o_row(history_next_y), .o_carry(unused_history_next_y_carry)
  );
  // 各坐标来源独立形成候选，历史行进位只参与末端掩码选择。
  (* keep = "true" *) logic [5:0] position_nonzero_group;
  logic position_nonzero;
  // 已保存位置按六位并行检查零值，完整判断只归并六个组结果。
  for (genvar group_index = 0; group_index < 6; group_index++) begin : g_position_nonzero
    localparam int p_first = group_index * 6;
    localparam int p_bits = 32 - p_first < 6 ? 32 - p_first : 6;
    assign position_nonzero_group[group_index] = |p_decode[p_first+:p_bits];
  end
  assign position_nonzero = |position_nonzero_group;
  assign fast_position_source[0] = position_nonzero && output_shape_o_valid;
  assign fast_position_source[1] = position_nonzero && !output_shape_o_valid && p_cache_hit;
  assign fast_position_source[2] = position_nonzero && !output_shape_o_valid &&
    !p_cache_hit && selected_history.valid;
  assign fast_position_power = {p_decode >> output_width_shift, p_decode & {16'd0, o_last_output_col_q}};
  assign fast_position_cache = {32'(p_cache_y), 32'(p_cache_x)};
  assign fast_position_history = {32'(i_last_y),
    p_register_descriptor ? 32'(selected_history.column) : 32'(history_column_sum)};
  assign fast_position_next_row = {32'(history_next_y),
    p_register_descriptor ? 32'(selected_history.column) : 32'(history_column_reduced)};
  assign fast_position_pair_value[0] = (fast_position_power & {64{fast_position_source[0]}}) |
    (fast_position_cache & {64{fast_position_source[1]}});
  assign fast_position_pair_value[1] =
    (fast_position_history & {64{fast_position_source[2] && !selected_history.row_advance}}) |
    (fast_position_next_row & {64{fast_position_source[2] && selected_history.row_advance}});
  // 十六位列、行坐标保留末级选择边界，完整高位随使用结果进行综合优化。
  for (genvar pair = 0; pair < 2; pair++) begin : g_position_pair
    for (genvar bit_index = 0; bit_index < 64; bit_index++) begin : g_bit
      (* keep = bit_index < 16 || (bit_index >= 32 && bit_index < 48) *) logic coordinate_bit;
      assign coordinate_bit = fast_position_pair_value[pair][bit_index];
      assign fast_position_pair[pair][bit_index] = coordinate_bit;
    end
  end
  assign fast_position_data = fast_position_pair[0] | fast_position_pair[1];
  // 四种列末结果先完成各自比较，位置来源只参与末级选择。
  assign fast_wrap_source = {fast_position_source, !(|fast_position_source)};
  assign fast_wrap_value[0] = i_c.output_w != 16'd0 && o_last_output_col_q == 16'd0;
  (* keep = "true" *) logic [5:0] power_wrap_group;
  logic cached_column_last;
  // 掩码位置的末列比较按三位并行形成关系，组结果只归并一次。
  for (genvar group_index = 0; group_index < 6; group_index++) begin : g_power_wrap
    localparam int p_first = group_index * 3;
    localparam int p_bits = 16 - p_first < 3 ? 16 - p_first : 3;
    assign power_wrap_group[group_index] =
        (p_decode[p_first+:p_bits] & o_last_output_col_q[p_first+:p_bits]) ==
        o_last_output_col_q[p_first+:p_bits];
  end
  conv_descriptor_match #(.p_width(16), .p_preserve_groups(1'b1)) u_cached_column_last (
    .i_a(p_cache_x), .i_b(o_last_output_col_q), .o_equal(cached_column_last)
  );
  assign fast_wrap_value[1] = &power_wrap_group;
  assign fast_wrap_value[2] = i_c.output_w != 16'd0 && cached_column_last;
  assign fast_wrap_value[3] = selected_history.wrap;
  onehot_mux #(.p_choices(4), .p_width(1)) u_fast_wrap (
    .i_select(fast_wrap_source), .i_data(fast_wrap_value), .o_data(fast_wrap_selected)
  );
  always_comb begin
    o_p_fast_valid=0;o_p_fast_y=0;o_p_fast_x=0;
    o_p_fast_wrap = i_c.output_w != 16'd0 && o_last_output_col_q == 16'd0;
    if (!position_nonzero) o_p_fast_valid=1;
    else if (output_shape_o_valid) begin
      // 二次幂输出宽度通过移位和掩码直接得到行列坐标。
      o_p_fast_valid=1;o_p_fast_y=p_decode>>output_width_shift;
      o_p_fast_x=p_decode&{16'd0,o_last_output_col_q};
      o_p_fast_wrap=o_p_fast_x=={16'd0,o_last_output_col_q};
    end
    else if (p_cache_hit) begin
      o_p_fast_valid=1;o_p_fast_y=32'(p_cache_y);o_p_fast_x=32'(p_cache_x);
      o_p_fast_wrap = i_c.output_w != 16'd0 && p_cache_x == o_last_output_col_q;
    end else if (selected_history.valid) begin
      o_p_fast_valid = 1'b1;
      o_p_fast_y = selected_history.row_advance ? 32'(history_next_y) : 32'(i_last_y);
      o_p_fast_x = 32'(selected_history.column);
      o_p_fast_wrap = selected_history.wrap;
    end
`ifdef SYNTHESIS
    {o_p_fast_y, o_p_fast_x} = fast_position_data;
    o_p_fast_wrap = fast_wrap_selected;
`endif
  end

  // 五位三通道解码使用完整的组合选择，同时输出商和余数。
  function automatic logic [5:0] divide_three_5(input logic [4:0] value);
    case (value)
      5'd0: divide_three_5 = {4'd0, 2'd0};
      5'd1: divide_three_5 = {4'd0, 2'd1};
      5'd2: divide_three_5 = {4'd0, 2'd2};
      5'd3: divide_three_5 = {4'd1, 2'd0};
      5'd4: divide_three_5 = {4'd1, 2'd1};
      5'd5: divide_three_5 = {4'd1, 2'd2};
      5'd6: divide_three_5 = {4'd2, 2'd0};
      5'd7: divide_three_5 = {4'd2, 2'd1};
      5'd8: divide_three_5 = {4'd2, 2'd2};
      5'd9: divide_three_5 = {4'd3, 2'd0};
      5'd10: divide_three_5 = {4'd3, 2'd1};
      5'd11: divide_three_5 = {4'd3, 2'd2};
      5'd12: divide_three_5 = {4'd4, 2'd0};
      5'd13: divide_three_5 = {4'd4, 2'd1};
      5'd14: divide_three_5 = {4'd4, 2'd2};
      5'd15: divide_three_5 = {4'd5, 2'd0};
      5'd16: divide_three_5 = {4'd5, 2'd1};
      5'd17: divide_three_5 = {4'd5, 2'd2};
      5'd18: divide_three_5 = {4'd6, 2'd0};
      5'd19: divide_three_5 = {4'd6, 2'd1};
      5'd20: divide_three_5 = {4'd6, 2'd2};
      5'd21: divide_three_5 = {4'd7, 2'd0};
      5'd22: divide_three_5 = {4'd7, 2'd1};
      5'd23: divide_three_5 = {4'd7, 2'd2};
      5'd24: divide_three_5 = {4'd8, 2'd0};
      5'd25: divide_three_5 = {4'd8, 2'd1};
      5'd26: divide_three_5 = {4'd8, 2'd2};
      5'd27: divide_three_5 = {4'd9, 2'd0};
      5'd28: divide_three_5 = {4'd9, 2'd1};
      5'd29: divide_three_5 = {4'd9, 2'd2};
      5'd30: divide_three_5 = {4'd10, 2'd0};
      5'd31: divide_three_5 = {4'd10, 2'd1};
      default: divide_three_5 = 'x;
    endcase
  endfunction

  assign q_decode_value = divide_three_5(i_q0[4:0]);
  assign o_k_decode_value = divide_three_5(i_tap0[4:0]);
  assign q_decode_o_quotient = q_decode_value[5:2];
  assign q_decode_o_remainder = q_decode_value[1:0];
  assign o_current_q_div3 = {1'b0, q_decode_o_quotient};
  assign o_current_q_remainder = {i_q0[15:5], 3'b000, q_decode_o_remainder};

  // 每级只保存当前阶段的算术结果，配置宽度扩展保持原有符号关系。

  // 配置阶段只在前端空闲时运行，四路坐标乘法器随后供运行阶段使用。
  always_comb begin
    coordinate_a[0] = i_ox_q;
    coordinate_b[0] = i_c.stride_w;
    coordinate_a[1] = i_oy_q;
    coordinate_b[1] = i_c.stride_h;
    coordinate_a[2] = i_kx_q;
    coordinate_b[2] = i_c.dilation_w;
    coordinate_a[3] = i_ky_q;
    coordinate_b[3] = i_c.dilation_h;
    if (o_cfg_prepare_phase == 3'd1) begin
      coordinate_a[0] = i_c.input_h;
      coordinate_b[0] = i_c.input_w;
      coordinate_a[1] = i_c.kernel_h;
      coordinate_b[1] = i_c.kernel_w;
      coordinate_a[2] = i_c.output_h;
      coordinate_b[2] = i_c.output_w;
      coordinate_a[3] = i_c.stride_h;
      coordinate_b[3] = i_c.input_w;
    end else if (o_cfg_prepare_phase == 3'd2) begin
      coordinate_a[0] = i_c.output_w;
      coordinate_b[0] = i_c.stride_w;
      coordinate_a[1] = i_c.kernel_w;
      coordinate_b[1] = i_c.dilation_w;
      coordinate_a[2] = i_c.dilation_h;
      coordinate_b[2] = i_c.input_w;
      coordinate_a[3] = i_c.stride_w;
      coordinate_b[3] = i_c.input_c;
    end else if (o_cfg_prepare_phase == 3'd3) begin
      coordinate_a[3] = i_c.dilation_w;
      coordinate_b[3] = i_c.input_c;
    end else if (i_state[$clog2(ADDRESS)]) begin
      coordinate_a[0] = i_iy[15:0];
      coordinate_b[0] = i_c.input_w;
    end
  end
  for (genvar product = 0; product < 4; product++) begin : g_coordinate
    assign o_shared_coordinate_product[product] =
        32'(coordinate_a[product]) * 32'(coordinate_b[product]);
  end

  // 两路完整乘积同时保留配置溢出检查所需的高位和运行地址所需的低位。
  always_comb begin
    channel_a[0] = i_pixel_index;
    channel_b[0] = i_c.input_c;
    channel_a[1] = i_pf1_pixel;
    channel_b[1] = i_c.input_c;
    if (o_cfg_prepare_phase == 3'd2) begin
      channel_a[0] = cfg_input_hw;
      channel_a[1] = cfg_kernel_taps;
      channel_b[1] = i_c.group_c;
    end else if (i_address_step_phase == 2'd1) begin
      channel_a[0] = i_row_wrap_pixels[31:0];
      channel_a[1] = i_tap_wrap_pixels[31:0];
    end else if (i_prefetch_phase == 4'd5) begin
      channel_a[1] = i_pf0_y;
      channel_b[1] = i_c.input_w;
    end
  end
  for (genvar product = 0; product < 2; product++) begin : g_channel
    // 两个十六位部分积在同一拍保存，下一阶段合并完整四十八位结果。
    always_ff @(posedge i_clk) begin
      channel_partial[product][0] <= channel_a[product][15:0] * channel_b[product];
      channel_partial[product][1] <= channel_a[product][31:16] * channel_b[product];
    end
    assign channel_upper[product] = channel_partial[product][1] +
        {16'd0, channel_partial[product][0][31:16]};
    assign o_shared_channel_product[product] =
        {channel_upper[product], channel_partial[product][0][15:0]};
  end

  assign o_coordinate_product_sum[0] = {1'b0, i_coordinate_product_q[0]} + {1'b0, i_coordinate_product_q[2]};
  assign o_coordinate_product_sum[1] = {1'b0, i_coordinate_product_q[1]} + {1'b0, i_coordinate_product_q[3]};
  assign o_coordinate_low_difference[0] = {1'b0, i_coordinate_sum_q[0][15:0]} - {1'b0, i_c.pad_left};
  assign o_coordinate_low_difference[1] = {1'b0, i_coordinate_sum_q[1][15:0]} - {1'b0, i_c.pad_top};
  logic [1:0][p_coord_w-17:0] coordinate_high;
  for (genvar axis = 0; axis < 2; axis++) begin : g_coordinate_padding
    // 低半字和借位已经保存，高位保留完整有符号坐标范围。
    assign coordinate_high[axis] = (p_coord_w-16)'(i_coordinate_sum_q[axis][32:16]) -
        (p_coord_w-16)'(i_coordinate_borrow_q[axis]);
  end
  assign o_coordinate_padded_x = $signed({coordinate_high[0], i_coordinate_sum_q[0][15:0]});
  assign o_coordinate_padded_y = $signed({coordinate_high[1], i_coordinate_sum_q[1][15:0]});
  assign group_channel_sum = i_channel_product + 32'(i_c.group_offset);
  assign o_group_address_sum = i_c.input_base + (group_channel_sum << i_c.input_s16);
  assign prefetch_channel_sum = i_pf_address_term + i_pf1_channel;
  assign o_prefetch_byte_offset = prefetch_channel_sum << i_c.input_s16;
  assign o_prefetch_address_sum = i_c.input_base + i_pf_address_term;
  assign o_prefetch_pixel_sum = o_shared_channel_product[1][31:0] + i_pf0_x;

  // 每个字节并行判断地址进位，最后合并四段结果。
  for (genvar byte_index = 0; byte_index < 4; byte_index++) begin : g_cfg_address_carry
    assign cfg_address_generate[byte_index] =
      i_c.input_base[8*byte_index+:8] > ~cfg_tensor_product[8*byte_index+:8];
    assign cfg_address_propagate[byte_index] =
      i_c.input_base[8*byte_index+:8] == ~cfg_tensor_product[8*byte_index+:8];
  end
  assign cfg_address_overflow = cfg_address_generate[3] ||
    (cfg_address_propagate[3] && cfg_address_generate[2]) ||
    (cfg_address_propagate[3] && cfg_address_propagate[2] && cfg_address_generate[1]) ||
    (cfg_address_propagate[3] && cfg_address_propagate[2] && cfg_address_propagate[1] && cfg_address_generate[0]);

  // 通道偏移、通道组长度与输入上限并行归并，保留完整和值的溢出判断。
  unsigned_sum_le #(.p_width(16)) u_cfg_group_within_input (
    .i_a(i_cfg.group_offset), .i_b(i_cfg.group_c),
    .i_limit(i_cfg.input_c), .o_within(cfg_group_within_input)
  );
  assign cfg_s8_offset_valid = $signed(i_cfg.input_offset) >= -127 && $signed(i_cfg.input_offset) <= 128;

  // 每四个维度独立检查非零值，三个组结果与通道范围并行准备。
  assign cfg_dimension_valid[0] = i_cfg.input_h!=0 && i_cfg.input_w!=0 &&
      i_cfg.input_c!=0 && i_cfg.group_c!=0;
  assign cfg_dimension_valid[1] = i_cfg.kernel_h!=0 && i_cfg.kernel_w!=0 &&
      i_cfg.output_h!=0 && i_cfg.output_w!=0;
  assign cfg_dimension_valid[2] = i_cfg.stride_h!=0 && i_cfg.stride_w!=0 &&
      i_cfg.dilation_h!=0 && i_cfg.dilation_w!=0;
  // 配置乘积经过寄存器后检查溢出。
  always_comb begin
    o_cfg_basic_valid=(&cfg_dimension_valid) && cfg_group_within_input;
    if (i_cfg.input_s16) o_cfg_basic_valid=o_cfg_basic_valid && i_cfg.input_offset==0 && !i_cfg.input_base[0];
    else o_cfg_basic_valid=o_cfg_basic_valid && cfg_s8_offset_valid;
    o_cfg_input_bytes={15'd0,cfg_tensor_product};
    o_cfg_red=cfg_reduction_product[31:0];
    o_cfg_positions=cfg_position_product;
    o_cfg_ok=cfg_basic_saved && cfg_tensor_product[48:32]==0 &&
      cfg_reduction_product[47:32]==0 && !cfg_address_overflow;
  end
  // 配置阶段和有效标志复位，乘积由对应阶段的时钟边沿保存。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_cfg_prepare_phase <= '0;
      cfg_basic_saved <= 1'b0;
    end else if (i_cfg_valid && i_cfg_ready) begin
      o_cfg_prepare_phase <= 1;
      cfg_basic_saved <= o_cfg_basic_valid;
    end else case (o_cfg_prepare_phase)
      1: o_cfg_prepare_phase <= 2;
      2: o_cfg_prepare_phase <= 3;
      3: o_cfg_prepare_phase <= 4;
      4: o_cfg_prepare_phase <= 0;
      default: ;
    endcase
  end
  always_ff @(posedge i_clk) begin
    if (!i_rst_n) begin
    end else case (o_cfg_prepare_phase)
      1: begin
        cfg_input_hw <= o_shared_coordinate_product[0];
        cfg_kernel_taps <= o_shared_coordinate_product[1];
        cfg_position_product <= o_shared_coordinate_product[2];
      end
      3: begin
        cfg_tensor_product <= {1'b0, o_shared_channel_product[0]} << i_c.input_s16;
        cfg_reduction_product <= o_shared_channel_product[1];
      end
      default: ;
    endcase
  end

  assign cfg_pixel_bytes = 32'(i_cfg.input_c) << i_cfg.input_s16;
  assign cfg_line_threshold[0] = 1'b1;
  for (genvar count = 1; count <= p_line_bytes; count++) begin : g_line_threshold
    // 两种元素宽度分别与常量比较，输入位宽选择只作用于最终标志。
    assign cfg_line_threshold[count] = i_cfg.input_s16 ?
      32'(i_cfg.input_c) <= 32'(((p_line_bytes-1)/count)/2) :
      32'(i_cfg.input_c) <= 32'((p_line_bytes-1)/count);
  end
  for (genvar count = 0; count <= p_line_bytes; count++) begin : g_line_select
    if (count == p_line_bytes) begin : g_last
      assign cfg_line_select[count] = cfg_line_threshold[count];
    end else begin : g_has_next
      assign cfg_line_select[count] = cfg_line_threshold[count] && !cfg_line_threshold[count+1];
    end
  end

  assign cfg_base_step = i_cfg.kernel_w == 16'd1 ? 32'(i_cfg.stride_w) : 32'(i_cfg.dilation_w);
  // 配置接收时保存行内像素数与基础步长，准备周期再完成最大值比较。
  always_comb begin
    cfg_line_pixels = 32'd0;
    for (int count = 0; count <= p_line_bytes; count++) begin
      cfg_line_pixels |= {32{cfg_line_select[count]}} & 32'(count+1);
    end
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_pf_step_base <= 32'd1;
      prefetch_line_pixels <= '0;
    end else if (i_cfg_valid && i_cfg_ready) begin
      o_pf_step_base <= cfg_base_step;
      prefetch_line_pixels <= p_prefetch_count_width'(cfg_line_pixels);
    end else if (o_cfg_prepare_phase == 3'd1) begin
      o_pf_step_base <= o_pf_step_base < 32'(prefetch_line_pixels) ?
        32'(prefetch_line_pixels) : o_pf_step_base;
    end
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin

      retire_enabled_q<=0;o_short_pixel_q<=0;retire_shift_q<=0;o_retire_last_row_q<=0;
      o_window_index_valid_q<=0;o_window_index_shift_q<=0;
      o_second_last_row_q<=0;o_last_output_col_q<=0;o_second_last_col_q<=0;
      o_last_kernel_col_q <= 16'd0;

      o_last_group_channel_q <= 16'hffff;
      o_group_nonzero_q <= 1'b0;

      o_kernel_width_valid_q <= 1'b0;
    end else if (i_cfg_valid && i_cfg_ready) begin

      retire_enabled_q<=stride_shape_o_valid;
      o_short_pixel_q<=cfg_pixel_bytes<p_line_bytes;
      o_window_index_valid_q<=i_cfg.windowed && i_cfg.input_base[$clog2(p_line_bytes)-1:0]==0 &&
        ((cfg_pixel_bytes>=p_line_bytes && (cfg_pixel_bytes&(p_line_bytes-1))==0) ||
         (pixel_shape_o_valid && cfg_pixel_bytes<p_line_bytes));
      // 短像素只检查缓存行范围内的位，最高有效位直接选择移位数。
      if (p_line_bytes > 0 && (p_line_bytes & (p_line_bytes - 1)) == 0) begin
        o_window_index_shift_q <= 5'd0;
        if (cfg_pixel_bytes < p_line_bytes) begin
          o_window_index_shift_q <= 5'($clog2(p_line_bytes));
          for (int bit_index = 1; bit_index < $clog2(p_line_bytes); bit_index++) begin
            if (cfg_pixel_bytes[bit_index])
              o_window_index_shift_q <= 5'($clog2(p_line_bytes) - bit_index);
          end
        end
      end else begin
        o_window_index_shift_q <= cfg_pixel_bytes < p_line_bytes ?
          power_shift(32'(p_line_bytes)) - power_shift(cfg_pixel_bytes) : 5'd0;
      end
      retire_shift_q<=4'(power_shift(32'(i_cfg.stride_h)));
      o_retire_last_row_q<=i_cfg.output_h-16'd1;
      o_second_last_row_q<=i_cfg.output_h-16'd2;
      o_last_output_col_q<=i_cfg.output_w-16'd1;o_second_last_col_q<=i_cfg.output_w-16'd2;
      o_last_kernel_col_q <= i_cfg.kernel_w - 16'd1;

      o_last_group_channel_q <= i_cfg.group_c - 16'd1;
      o_group_nonzero_q <= |i_cfg.group_c;

      o_kernel_width_valid_q <= i_cfg.kernel_w != 16'd0;
    end
  end

  assign epoch_i_a[0] = {16'd0, i_window_next_ch};
  assign epoch_i_a[1] = {16'd0, i_ch0_q};
  assign epoch_i_a[2] = i_ch;
  assign stream_epoch_xor = {16'd0, i_c.group_offset} ^ i_ch ^ 32'(i_chunk_count);
  assign stream_epoch_carry = (({16'd0, i_c.group_offset} & i_ch) |
    ({16'd0, i_c.group_offset} & 32'(i_chunk_count)) | (i_ch & 32'(i_chunk_count))) << 1;
  assign epoch_i_a[3] = stream_epoch_xor;
  assign epoch_i_a[4] = i_pfa_channel;
  assign epoch_i_b[0] = {16'd0, i_c.group_offset};
  assign epoch_i_b[1] = {16'd0, i_c.group_offset};
  assign epoch_i_b[2] = {16'd0, i_c.group_offset};
  assign epoch_i_b[3] = stream_epoch_carry;
  assign epoch_i_b[4] = {16'd0, i_c.group_offset};
  assign epoch_i_carry = 1'b0;
  for (genvar candidate = 0; candidate < 5; candidate++) begin : g_epoch_candidate
    if (candidate == 3 && p_lanes <= 16) begin : g_stream_shared
      logic [17:0] stream_channel_sum;
      // 高段和值由所有短步长共用，低段及其进位区间先行计算。
      conv_stream_epoch_sum #(.p_lanes(p_lanes)) u_stream_epoch (
        .i_offset(i_c.group_offset), .i_channel(i_ch[17:0]),
        .i_selected(i_chunk_selected), .o_sum(stream_channel_sum)
      );
      assign o_epoch_o_sum[candidate] = {14'd0, stream_channel_sum};
      assign unused_epoch_carry[candidate] = 1'b0;
    end else begin : g_general
      parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_sum (
        .i_a(epoch_i_a[candidate]), .i_b(epoch_i_b[candidate]), .i_carry(epoch_i_carry),
        .o_sum(o_epoch_o_sum[candidate]), .o_carry(unused_epoch_carry[candidate])
      );
    end
  end
  assign stream_channel_i_a = i_ch;
  assign stream_channel_i_b = 32'(i_chunk_count);
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_stream_channel (
    .i_a(stream_channel_i_a), .i_b(stream_channel_i_b), .i_carry(epoch_i_carry),
    .o_sum(o_stream_channel_full), .o_carry(unused_stream_channel_carry)
  );

  // 当前项与新描述符分别完成索引移位和纪元运算，描述符有效条件只控制末级选择。
  assign incoming_epoch_channel = i_incoming_next_position_fast ? o_epoch_o_sum[0] : o_epoch_o_sum[1];
  assign o_incoming_req_index = o_short_pixel_q ? i_incoming_pixel >> o_window_index_shift_q : i_incoming_pixel;
  assign o_incoming_req_epoch = o_short_pixel_q ? 32'd0 :
    (incoming_epoch_channel << i_c.input_s16) >> $clog2(p_line_bytes);

endmodule

`default_nettype wire
