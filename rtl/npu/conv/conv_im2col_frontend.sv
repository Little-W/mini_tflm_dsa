// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 隐式 im2col 前端接收 IA 分块描述符，按原矩阵顺序生成校正后的十六位数据。
// 配置、坐标、窗口描述符、预取和流式范围分别由独立模块处理。
module conv_im2col_frontend #(
  parameter int SIZE=16,
  parameter int SLOT_W=3,
  parameter int LANES=2,       // 独立 IA 存储组的校正数据写入通道数。
  parameter int CACHE_SETS=128,
  parameter int CACHE_WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int NARROW_LANES=BUS_WIDTH/8,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter bit REGISTER_CACHE_REQUEST=1'b1,
  // 描述符准备、请求保存和响应队列分别选择寄存边界。
  parameter bit REGISTER_DESCRIPTOR=1'b0,
  parameter bit REGISTER_ROW_ADDRESS=REGISTER_DESCRIPTOR,
  parameter int CACHE_RESPONSE_DEPTH=1,
  parameter int CW=$clog2(SIZE),
  parameter int RW=$clog2(SIZE+1)
) (
  input wire logic clk, rst_n,
  input wire logic cfg_valid,
  output logic cfg_ready,
  input wire conv_im2col_pkg::conv_cfg_t cfg,
  // IA 调度上下文中的组数为零时关闭几何预测，支持任意描述符顺序。
  input wire logic [31:0] cfg_sched_r = 32'd0,
  input wire logic [31:0] cfg_sched_groups = 32'd0,
  input wire logic tile_valid,
  output logic tile_ready,
  input wire logic [31:0] tile_p0, tile_q0,
  input wire logic [RW-1:0] tile_rows,
  input wire logic [RW-1:0] tile_cols = '0, // 零值选择完整的 SIZE 列。
  input wire logic [SLOT_W-1:0] tile_slot,
  input wire logic [31:0] tile_group = 32'd0,
  input wire logic tile_narrow = 1'b0,
  output logic wr_valid,
  input wire logic wr_ready,
  output logic [SLOT_W-1:0] wr_slot,
  output logic [CW-1:0] wr_row, wr_col,
  output logic signed [15:0] wr_data [LANES],
  output logic [LANES-1:0] wr_mask,
  output logic tile_done, tile_error, error, busy,
  output logic wr_last,
  output logic arvalid,
  input wire logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input wire logic rvalid,
  output logic rready,
  input wire logic [BUS_WIDTH-1:0] rdata,
  input wire logic [1:0] rresp,
  input wire logic rlast
);

  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_lane_bytes = LANES <= 4 ? 4 : (1 << $clog2(LANES));
  localparam int p_cache_read_bytes = p_lane_bytes < LINE_BYTES ? p_lane_bytes : LINE_BYTES;
  localparam int p_cache_read_width = 8 * p_cache_read_bytes;
  localparam int p_word_shift = $clog2(p_cache_read_bytes);
  localparam int p_row_low_w = RW < 32 ? RW : 31;
  localparam int p_row_high_w = 32 - p_row_low_w;
  localparam int TILE_COUNT_W = $clog2(SIZE+1);
  localparam int CHUNK_COUNT_W = $clog2(LANES+1);
  localparam int p_saved_group_lanes = LANES <= 16 ? p_lane_bytes : 4;
  localparam int COORD_W = 35;
  localparam int p_prepared_count_w = TILE_COUNT_W;
  localparam int p_prepared_slot_w = SLOT_W;
  localparam int p_prepared_coord_w = COORD_W;
  `include "conv_im2col_prepared_tile.svh"
  (* fsm_encoding = "none" *) st_t state;
  logic word_output_q;
  st_t descriptor_state;
  st_t operation_state;
  st_t selected_state;
  logic descriptor_commit_eligible;
  logic stream_response_error;
  logic stream_output_accept;
  logic stream_operation_accept;
  logic descriptor_state_context;
  logic state_update;
  conv_cfg_t c;
  logic configured;
  logic cfg_ok;
  logic cfg_basic_valid;
  logic [2:0] cfg_prepare_phase;
  logic [63:0] cfg_input_bytes;
  logic [31:0] cfg_red;
  logic [31:0] cfg_positions;
  logic [31:0] reduction_len;
  logic [31:0] position_count;
  logic [31:0] tensor_bytes;
  logic [p_row_high_w-1:0] position_high_minus_one_q;
  logic tile_rows_in_range;
  logic tile_q_before_end;
  logic [15:0] last_group_channel_q;
  logic group_nonzero_q;
  logic [5:0][15:0] group_range_channel;
  logic [16:0] initial_group_remaining;
  logic [16:0] window_group_remaining_q;
  logic [5:0][p_saved_group_lanes:0] group_range_next;
  logic [31:0] p0;
  logic [31:0] q0;
  logic [31:0] tap0;
  logic [32:0] next_group_q;
  logic [32:0] skip_group_q;
  logic [32:0] cfg_next_group;
  logic [32:0] cfg_skip_group;
  logic [TILE_COUNT_W-1:0] row_idx;
  logic [TILE_COUNT_W-1:0] col_idx;
  logic [TILE_COUNT_W-1:0] rows_q;
  logic [TILE_COUNT_W-1:0] cols_q;
  logic [TILE_COUNT_W-1:0] active_cols_q;
  logic [TILE_COUNT_W-1:0] next_row_idx;
  logic row_last_q;
  logic next_row_last;
  logic unused_row_index_carry;
  logic past_active_q;
  logic narrow_output;
  logic [LANES-1:0] chunk_lane_allowed;
  logic [LANES:0] chunk_selected;
  logic chunk_reaches_end;
  logic [15:0] ox_q;
  logic [15:0] oy_q;
  logic [15:0] ky_q;
  logic [15:0] kx_q;
  logic [15:0] ch_q;
  logic [15:0] ky0_q;
  logic [15:0] kx0_q;
  logic [15:0] ch0_q;
  logic [31:0] ox;
  logic [31:0] oy;
  logic [31:0] ky;
  logic [31:0] kx;
  logic [31:0] ch;
  logic [31:0] ky0;
  logic [31:0] kx0;
  logic [31:0] ch0;
  logic [32:0] q_current;
  logic signed [COORD_W-1:0] ix;
  logic signed [COORD_W-1:0] iy;
  logic [31:0] pixel_index;
  logic [3:0][31:0] coordinate_product_q;
  logic [1:0][32:0] coordinate_sum_q;
  logic [1:0] coordinate_borrow_q;
  logic [1:0][16:0] coordinate_low_difference;
  logic [1:0] address_axis_valid;
  logic address_position_valid;
  logic address_reduction_valid, unused_address_reduction_equal;
  logic [31:0] pixel_product;
  logic [31:0] channel_product;
  logic [31:0] group_base_addr;
  logic [31:0] channel_addr;
  logic [31:0] tap_group_base;
  logic [31:0] row_group_base;
  logic descriptor_payload_context;
  logic [15:0] kernel_column_payload, kernel_column_reference;
  logic [1:0][COORD_W-1:0] coordinate_payload;
  logic [31:0] pixel_payload, tap_group_payload, row_group_payload;
  logic [31:0] tap_group_reference, row_group_reference;
  logic [31:0] next_row_group_base;
  logic pad_q;
  logic [31:0] addr;
  logic [p_cache_read_width-1:0] word_buf;
  logic [31:0] word_addr;
  logic word_valid;
  logic current_word_hit;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  logic [SLOT_W-1:0] slot_q;
  logic [31:0] decode_index;
  logic [31:0] decode_outer;
  logic [31:0] decode_inner;
  logic [2:0] decode_end_o_equal;
  logic cache_cfg_ready;
  logic cache_req_ready;
  logic cache_rsp_valid;
  logic unused_cache_rsp_error;
  logic cache_rsp_success;
  logic cache_rsp_failure;
  logic cache_req_valid;
  logic request_tap_context;
  logic cache_rsp_ready;
  logic stream_next_request;
  logic next_row_request;
  logic request_stream_context;
  logic request_row_context;
  logic request_row_metadata_context;
  logic request_descriptor_metadata_context;
  logic [31:0] request_epoch_selected;
  logic [COORD_W-1:0] request_y_selected;
  logic [31:0] request_index_selected;
  logic active_after_chunk;
  logic [p_word_shift+1:0] byte_offset_sum;
  logic incoming_context;
  logic incoming_word_hit;
  logic finishing_tile;
  logic descriptor_response_forward;
  logic incoming_next_tile_fast;
  logic incoming_next_position_fast;
  logic incoming_skip_tap;
  logic [15:0] window_next_x;
  logic [15:0] window_next_y;
  logic [15:0] window_next_ch;
  logic [1:0] incoming_tile_group_fits;
  logic cache_port_valid;
  logic preview_capture_valid;
  logic [31:0] cache_req_addr;
  logic [31:0] cache_req_addr_reference;
  logic [31:0] stream_request_addr;
  logic request_pending;
  logic cache_port_ready;
  logic [31:0] current_req_index;
  logic [31:0] current_req_epoch;
  logic [31:0] request_addr_q;
  logic [31:0] request_index_q;
  logic [31:0] request_epoch_q;
  logic [15:0] request_y_q;
  logic [31:0] request_progress_q;
  logic short_pixel_q;
  logic [15:0] retire_last_row_q;
  logic [15:0] second_last_row_q;
  logic [15:0] last_output_col_q;
  logic [15:0] second_last_col_q;
  logic [15:0] last_kernel_col_q;
  logic kernel_width_valid_q;
  logic request_geometry_q;
  logic request_event_first_q;
  logic request_index_valid_q;
  logic [p_cache_read_width-1:0] cache_rsp_data;
  logic pred_cfg_eligible;
  logic pred_enabled;
  logic pred_busy;
  logic pred_done;
  logic pred_start;
  logic pred_cfg_busy;
  logic cache_cfg_pending;
  logic cache_config_valid;
  logic pred_cfg_pending;
  logic [31:0] pred_rank;
  logic [31:0] groups_q;
  logic unused_predictor_position_carry;
  logic geometry_tile;
  logic line_hint_valid;
  logic cache_hint_pending;
  logic [31:0] line_hint_rank;
  logic [3:0] p_cache_valid;
  logic last_p_valid;
  logic [31:0] last_p;
  logic last_p_overflow_q;
  logic history_limit_carry;
  logic [15:0] last_y;
  logic [15:0] last_x;
  logic p_fast_valid;
  logic p_fast_wrap;
  logic [31:0] p_fast_y;
  logic [31:0] p_fast_x;
  logic incoming_fast;
  logic incoming_padding;
  logic incoming_tap_wrap;
  logic [31:0] incoming_ch;
  logic [31:0] incoming_ky;
  logic [31:0] incoming_kx;
  logic [31:0] incoming_addr;
  logic signed [COORD_W-1:0] incoming_ix;
  logic signed [COORD_W-1:0] incoming_iy;
  logic [31:0] incoming_pixel;
  logic [1:0] p_cache_select;
  logic [31:0] req_index;
  logic [31:0] req_epoch;
  logic [31:0] request_retire;
  logic [1:0][31:0] retirement_result;
  logic req_index_valid;
  logic window_index_valid_q;
  logic [4:0] window_index_shift_q;
  logic pf_valid;
  logic unused_pf_ready;
  logic [31:0] pf_addr;
  logic [31:0] pf_index;
  logic [31:0] pf_epoch;
  logic pf_index_valid;
  logic [3:0] prefetch_phase;
  logic [31:0] pf_address_term;
  logic signed [COORD_W-1:0] pfa_y;
  logic [31:0] pfa_channel;
  logic [31:0] pf0_x;
  logic [31:0] pf0_y;
  logic [31:0] pf1_pixel;
  logic [31:0] pf1_channel;
  logic [31:0] pf1_retire;
  logic [31:0] pf1_ref_addr;
  logic [31:0] pf1_ref_index;
  logic [31:0] pf1_ref_epoch;
  logic [31:0] pf1_ref_retire;
  logic pf1_ref_index_valid;
  logic pf1_fragment;
  logic pf1_coordinate_valid;
  logic [31:0] pf_step_base;
  logic fragment_image_fits;
  logic [4:0] current_q_div3;
  logic [15:0] current_q_remainder;
  logic signed [COORD_W-1:0] request_y;
  logic [31:0] incoming_req_index;
  logic [9:0][31:0] incoming_pixel_candidates;
  logic [9:0][31:0] incoming_address_candidates;
  logic [9:0][31:0] incoming_group_candidates;
  logic [9:0][15:0] incoming_kernel_x_candidates;
  logic [9:0][COORD_W-1:0] incoming_y_candidates;
  logic [9:0] incoming_pixel_select;
  logic [31:0] request_output_y;
  logic [31:0] incoming_req_epoch;
  logic [1:0][31:0] incoming_epoch_candidate;
  logic [31:0] request_address_value;
  logic [31:0] request_address_reference;
  logic [4:0][31:0] epoch_o_sum;
  logic [31:0] stream_channel_full;
  logic signed [32:0] row_pair_dx;
  logic [COORD_W-1:0] bound_sum [7];
  logic [6:0] bound_valid;
  logic [2:0] skip_bound_valid;
  logic [2:0] window_padding;
  logic next_word_o_equal;
  logic incoming_word_o_equal;
  logic incoming_live_word_o_equal;
  logic [1:0] address_step_phase;
  logic signed [32:0] row_wrap_dx;
  logic signed [32:0] tap_wrap_dx;
  logic signed [32:0] row_y_pixels;
  logic signed [32:0] tap_y_pixels;
  logic signed [32:0] row_wrap_pixels;
  logic signed [32:0] tap_wrap_pixels;
  logic [31:0] row_step_bytes;
  logic [31:0] tap_step_bytes;
  logic [31:0] row_wrap_bytes;
  logic [31:0] tap_wrap_bytes;
  logic signed [32:0] row_pair_dx_sum;
  logic signed [32:0] row_wrap_pixel_sum;
  logic signed [32:0] tap_wrap_pixel_sum;
  logic signed [COORD_W-1:0] tap_pair_dx;
  logic [31:0] tap_pair_pixels;
  logic [31:0] tap_pair_bytes;
  logic row_base_valid;
  logic coordinate_address_valid;
  logic row_coordinate_valid;
  logic signed [COORD_W-1:0] row_base_ix;
  logic signed [COORD_W-1:0] row_base_iy;
  logic [31:0] row_base_pixel;
  logic [31:0] row_base_addr;
  logic row_wrap;
  logic tap_wrap;
  logic next_row_padding;
  logic next_tap_padding;
  logic row_wrap_q;
  logic [5:0] row_wrap_candidate;
  logic tap_wrap_q;
  logic incoming_tap_wrap_q;
  logic [8:0] tap_wrap_candidate;
  logic [3:0][5:0] wrap_update_candidate;
  logic [2:0] wrap_write;
  logic [2:0] wrap_value;
  logic wrap_cfg_fire;
  logic wrap_descriptor_check;
  logic wrap_running_state;
  logic tap_next_o_equal;
  logic row_next_o_equal;
  logic signed [COORD_W-1:0] next_row_ix;
  logic signed [COORD_W-1:0] next_row_iy;
  logic signed [COORD_W-1:0] next_tap_ix;
  logic signed [COORD_W-1:0] next_tap_iy;
  logic [31:0] next_row_pixel;
  logic [31:0] next_tap_pixel;
  logic [31:0] next_row_addr;
  logic [31:0] next_tap_addr;
  logic [32:0] next_q_current;
  logic channel_accept_fire;
  logic tile_ready_context;
  logic [1:0] tile_context_ready;
  logic tile_ready_static;
  logic tile_admission_ready;
  prepared_tile_t committing_tile;
  logic tile_prepared_valid;
  logic tile_commit;
  logic committing_saved_word_hit;
  logic committing_live_word_hit;
  logic descriptor_padding;
  logic [p_cache_read_width-1:0] descriptor_word_data_q;
  logic cfg_output_last;
  logic cfg_kernel_last;
  logic cfg_incoming_kernel_last;
  logic [1:0] next_row_word_match;
  logic [1:0] incoming_advanced_word_match;
  logic group_shape_o_valid;
  logic kernel_shape_o_valid;
  logic [4:0] group_width_shift;
  logic [4:0] kernel_width_shift;
  logic [5:0] k_decode_value;
  logic [1:0][32:0] coordinate_product_sum;
  logic signed [COORD_W-1:0] coordinate_padded_x;
  logic signed [COORD_W-1:0] coordinate_padded_y;
  logic [31:0] group_address_sum;
  logic [31:0] prefetch_address_sum;
  logic [31:0] prefetch_byte_offset;
  logic [31:0] prefetch_pixel_sum;
  logic [3:0][31:0] shared_coordinate_product;
  logic [1:0][47:0] shared_channel_product;
  logic [15:0] kernel_decode_column;
  logic kernel_decode_last;
  logic [2:0][5:0] cfg_idle_groups;
  logic [2:0] cfg_idle_group_clear;
  logic group_end_o_equal;
  logic [31:0] decode_index_advance;
  logic [31:0] decode_inner_advance;
  logic [p_row_high_w-1:0] position_high_minus_one;
  st_t stream_advance_state;
  conv_im2col_geometry #(
    .p_size(SIZE), .p_slot_w(SLOT_W), .p_lanes(LANES), .p_line_bytes(LINE_BYTES), .p_register_cache_request(REGISTER_CACHE_REQUEST), .p_register_descriptor(REGISTER_DESCRIPTOR), .p_cw(CW)
  ) u_geometry (
    .i_clk(clk),
    .i_rst_n(rst_n),
    .i_cfg_valid(cfg_valid),
    .i_cfg_ready(cfg_ready),
    .i_cfg(cfg),
    .i_state(state),
    .i_c(c),
    .o_cfg_ok(cfg_ok),
    .o_cfg_basic_valid(cfg_basic_valid),
    .o_cfg_prepare_phase(cfg_prepare_phase),
    .o_cfg_input_bytes(cfg_input_bytes),
    .o_cfg_red(cfg_red),
    .o_cfg_positions(cfg_positions),
    .o_last_group_channel_q(last_group_channel_q),
    .o_group_nonzero_q(group_nonzero_q),
    .i_p0(p0),
    .i_q0(q0),
    .i_tap0(tap0),
    .i_ox_q(ox_q),
    .i_oy_q(oy_q),
    .i_ky_q(ky_q),
    .i_kx_q(kx_q),
    .i_ch_q(ch_q),
    .i_kx0_q(kx0_q),
    .i_ch0_q(ch0_q),
    .i_ch(ch),
    .i_ix(ix),
    .i_iy(iy),
    .i_pixel_index(pixel_index),
    .i_coordinate_product_q(coordinate_product_q),
    .i_coordinate_sum_q(coordinate_sum_q),
    .i_coordinate_borrow_q(coordinate_borrow_q),
    .i_channel_product(channel_product),
    .i_group_base_addr(group_base_addr),
    .o_channel_addr(channel_addr),
    .i_tap_group_base(tap_group_base),
    .i_row_group_base(row_group_base),
    .o_next_row_group_base(next_row_group_base),
    .i_addr(addr),
    .i_chunk_count(chunk_count),
    .i_chunk_selected(chunk_selected),
    .i_decode_index(decode_index),
    .i_decode_outer(decode_outer),
    .i_decode_inner(decode_inner),
    .o_decode_end_o_equal(decode_end_o_equal),
    .i_incoming_next_position_fast(incoming_next_position_fast),
    .i_window_next_ch(window_next_ch),
    .i_request_y_q(request_y_q),
    .o_short_pixel_q(short_pixel_q),
    .o_retire_last_row_q(retire_last_row_q),
    .o_second_last_row_q(second_last_row_q),
    .o_last_output_col_q(last_output_col_q),
    .o_second_last_col_q(second_last_col_q),
    .o_last_kernel_col_q(last_kernel_col_q),
    .o_kernel_width_valid_q(kernel_width_valid_q),
    .i_p_cache_valid(p_cache_valid),
    .i_last_p_valid(last_p_valid),
    .i_last_p(last_p),
    .i_last_p_overflow_q(last_p_overflow_q),
    .o_history_limit_carry(history_limit_carry),
    .i_last_y(last_y),
    .i_last_x(last_x),
    .o_p_fast_valid(p_fast_valid),
    .o_p_fast_wrap(p_fast_wrap),
    .o_p_fast_y(p_fast_y),
    .o_p_fast_x(p_fast_x),
    .i_incoming_pixel(incoming_pixel),
    .o_p_cache_select(p_cache_select),
    .o_request_retire(request_retire),
    .o_retirement_result(retirement_result),
    .o_window_index_valid_q(window_index_valid_q),
    .o_window_index_shift_q(window_index_shift_q),
    .i_prefetch_phase(prefetch_phase),
    .i_pf_address_term(pf_address_term),
    .i_pfa_y(pfa_y),
    .i_pfa_channel(pfa_channel),
    .i_pf0_x(pf0_x),
    .i_pf0_y(pf0_y),
    .i_pf1_pixel(pf1_pixel),
    .i_pf1_channel(pf1_channel),
    .o_pf_step_base(pf_step_base),
    .o_current_q_div3(current_q_div3),
    .o_current_q_remainder(current_q_remainder),
    .i_request_y(request_y),
    .o_incoming_req_index(),
    .o_incoming_req_epoch(),
    .o_epoch_o_sum(epoch_o_sum),
    .o_stream_channel_full(stream_channel_full),
    .o_bound_sum(bound_sum),
    .o_bound_valid(bound_valid),
    .o_skip_bound_valid(skip_bound_valid),
    .o_window_padding(window_padding),
    .o_next_word_o_equal(next_word_o_equal),
    .i_address_step_phase(address_step_phase),
    .i_row_wrap_dx(row_wrap_dx),
    .i_tap_wrap_dx(tap_wrap_dx),
    .i_row_wrap_pixels(row_wrap_pixels),
    .i_tap_wrap_pixels(tap_wrap_pixels),
    .i_row_step_bytes(row_step_bytes),
    .i_tap_step_bytes(tap_step_bytes),
    .i_row_wrap_bytes(row_wrap_bytes),
    .i_tap_wrap_bytes(tap_wrap_bytes),
    .o_tap_pair_dx(tap_pair_dx),
    .o_tap_pair_pixels(tap_pair_pixels),
    .o_tap_pair_bytes(tap_pair_bytes),
    .i_row_base_ix(row_base_ix),
    .i_row_base_iy(row_base_iy),
    .i_row_base_pixel(row_base_pixel),
    .i_row_base_addr(row_base_addr),
    .o_row_wrap(row_wrap),
    .o_tap_wrap(tap_wrap),
    .o_next_row_padding(next_row_padding),
    .o_next_tap_padding(next_tap_padding),
    .i_row_wrap_q(row_wrap_q),
    .i_tap_wrap_q(tap_wrap_q),
    .o_tap_next_o_equal(tap_next_o_equal),
    .o_row_next_o_equal(row_next_o_equal),
    .o_next_row_ix(next_row_ix),
    .o_next_row_iy(next_row_iy),
    .o_next_tap_ix(next_tap_ix),
    .o_next_tap_iy(next_tap_iy),
    .o_next_row_pixel(next_row_pixel),
    .o_next_tap_pixel(next_tap_pixel),
    .o_next_row_addr(next_row_addr),
    .o_next_tap_addr(next_tap_addr),
    .i_committing_tile_packed(committing_tile),
    .i_tile_commit(tile_commit),
    .o_cfg_output_last(cfg_output_last),
    .o_cfg_kernel_last(cfg_kernel_last),
    .o_cfg_incoming_kernel_last(cfg_incoming_kernel_last),
    .o_group_shape_o_valid(group_shape_o_valid),
    .o_kernel_shape_o_valid(kernel_shape_o_valid),
    .o_group_width_shift(group_width_shift),
    .o_kernel_width_shift(kernel_width_shift),
    .o_k_decode_value(k_decode_value),
    .o_coordinate_product_sum(coordinate_product_sum),
    .o_coordinate_low_difference(coordinate_low_difference),
    .o_coordinate_padded_x(coordinate_padded_x),
    .o_coordinate_padded_y(coordinate_padded_y),
    .o_group_address_sum(group_address_sum),
    .o_prefetch_address_sum(prefetch_address_sum),
    .o_prefetch_byte_offset(prefetch_byte_offset),
    .o_prefetch_pixel_sum(prefetch_pixel_sum),
    .o_shared_coordinate_product(shared_coordinate_product),
    .o_shared_channel_product(shared_channel_product)
  );

  conv_im2col_descriptor #(
    .p_size(SIZE), .p_slot_w(SLOT_W), .p_lanes(LANES), .p_line_bytes(LINE_BYTES), .p_cache_policy(CACHE_POLICY), .p_register_descriptor(REGISTER_DESCRIPTOR), .p_rw(RW)
  ) u_descriptor (
    .i_clk(clk),
    .i_rst_n(rst_n),
    .i_cfg_valid(cfg_valid),
    .i_cfg_ready(cfg_ready),
    .i_tile_valid(tile_valid),
    .i_tile_ready(tile_ready),
    .i_tile_finish(finishing_tile),
    .i_tile_p0(tile_p0),
    .i_tile_q0(tile_q0),
    .i_tile_rows(tile_rows),
    .i_tile_cols(tile_cols),
    .i_tile_slot(tile_slot),
    .i_tile_group(tile_group),
    .i_tile_narrow(tile_narrow),
    .i_error(error),
    .i_state(state),
    .i_c(c),
    .i_reduction_len(reduction_len),
    .i_position_count(position_count),
    .i_position_high_minus_one_q(position_high_minus_one_q),
    .o_tile_rows_in_range(tile_rows_in_range),
    .o_tile_q_before_end(tile_q_before_end),
    .i_last_group_channel_q(last_group_channel_q),
    .i_group_nonzero_q(group_nonzero_q),
    .i_initial_group_remaining(initial_group_remaining),
    .o_window_group_remaining_q(window_group_remaining_q),
    .i_group_range_next(group_range_next),
    .i_p0(p0),
    .i_q0(q0),
    .i_tap0(tap0),
    .i_next_group_q(next_group_q),
    .i_skip_group_q(skip_group_q),
    .i_rows_q(rows_q),
    .i_cols_q(cols_q),
    .i_ox_q(ox_q),
    .i_oy_q(oy_q),
    .i_ky0_q(ky0_q),
    .i_kx0_q(kx0_q),
    .i_ch0_q(ch0_q),
    .i_ky0(ky0),
    .i_kx0(kx0),
    .i_ch0(ch0),
    .i_ix(ix),
    .i_iy(iy),
    .i_row_group_base(row_group_base),
    .i_next_row_group_base(next_row_group_base),
    .i_addr(addr),
    .i_word_buf(word_buf),
    .i_word_addr(word_addr),
    .i_word_valid(word_valid),
    .i_incoming_word_hit(incoming_word_hit),
    .i_descriptor_response_forward(descriptor_response_forward),
    .o_incoming_next_tile_fast(incoming_next_tile_fast),
    .o_incoming_next_position_fast(incoming_next_position_fast),
    .o_incoming_skip_tap(incoming_skip_tap),
    .o_window_next_x(window_next_x),
    .o_window_next_y(window_next_y),
    .o_window_next_ch(window_next_ch),
    .o_incoming_pixel_candidates(incoming_pixel_candidates),
    .o_incoming_address_candidates(incoming_address_candidates),
    .o_incoming_group_candidates(incoming_group_candidates),
    .o_incoming_kernel_x_candidates(incoming_kernel_x_candidates),
    .o_incoming_y_candidates(incoming_y_candidates),
    .o_incoming_pixel_select(incoming_pixel_select),
    .i_incoming_tile_group_fits(incoming_tile_group_fits),
    .i_last_output_col_q(last_output_col_q),
    .i_last_kernel_col_q(last_kernel_col_q),
    .i_cache_rsp_data(cache_rsp_data),
    .i_pred_enabled(pred_enabled),
    .i_groups_q(groups_q),
    .i_geometry_tile(geometry_tile),
    .o_incoming_fast(incoming_fast),
    .o_incoming_padding(incoming_padding),
    .i_incoming_tap_wrap(incoming_tap_wrap),
    .o_incoming_ch(incoming_ch),
    .o_incoming_ky(incoming_ky),
    .o_incoming_kx(incoming_kx),
    .o_incoming_addr(incoming_addr),
    .o_incoming_ix(incoming_ix),
    .o_incoming_iy(incoming_iy),
    .o_incoming_pixel(incoming_pixel),
    .i_bound_sum(bound_sum),
    .i_bound_valid(bound_valid),
    .i_skip_bound_valid(skip_bound_valid),
    .i_window_padding(window_padding),
    .o_incoming_word_o_equal(incoming_word_o_equal),
    .o_incoming_live_word_o_equal(incoming_live_word_o_equal),
    .i_row_wrap_dx(row_wrap_dx),
    .i_tap_wrap_dx(tap_wrap_dx),
    .i_tap_wrap_pixels(tap_wrap_pixels),
    .i_row_step_bytes(row_step_bytes),
    .i_tap_step_bytes(tap_step_bytes),
    .i_row_wrap_bytes(row_wrap_bytes),
    .i_tap_wrap_bytes(tap_wrap_bytes),
    .i_tap_pair_dx(tap_pair_dx),
    .i_tap_pair_pixels(tap_pair_pixels),
    .i_tap_pair_bytes(tap_pair_bytes),
    .i_row_base_valid(row_base_valid),
    .i_coordinate_address_valid(coordinate_address_valid),
    .i_row_base_ix(row_base_ix),
    .i_row_base_iy(row_base_iy),
    .i_row_base_pixel(row_base_pixel),
    .i_row_base_addr(row_base_addr),
    .i_row_wrap(row_wrap),
    .i_next_row_padding(next_row_padding),
    .i_row_next_o_equal(row_next_o_equal),
    .i_next_row_ix(next_row_ix),
    .i_next_row_iy(next_row_iy),
    .i_next_row_pixel(next_row_pixel),
    .i_next_row_addr(next_row_addr),
    .o_channel_accept_fire(channel_accept_fire),
    .i_tile_ready_context(tile_ready_context),
    .o_committing_tile_packed(committing_tile),
    .o_tile_prepared_valid(tile_prepared_valid),
    .o_tile_commit(tile_commit),
    .o_committing_saved_word_hit(committing_saved_word_hit),
    .o_committing_live_word_hit(committing_live_word_hit),
    .o_descriptor_padding(descriptor_padding),
    .o_descriptor_word_data_q(descriptor_word_data_q),
    .o_next_row_word_match(next_row_word_match),
    .o_incoming_advanced_word_match(incoming_advanced_word_match),
    .o_kernel_decode_column(kernel_decode_column),
    .o_kernel_decode_last(kernel_decode_last)
  );

  conv_im2col_stream #(
    .p_size(SIZE), .p_slot_w(SLOT_W), .p_lanes(LANES), .p_line_bytes(LINE_BYTES), .p_bus_width(BUS_WIDTH), .p_narrow_lanes(NARROW_LANES), .p_register_cache_request(REGISTER_CACHE_REQUEST), .p_register_descriptor(REGISTER_DESCRIPTOR), .p_register_row_address(REGISTER_ROW_ADDRESS), .p_rw(RW)
  ) u_stream (
    .i_clk(clk),
    .i_rst_n(rst_n),
    .i_cfg_valid(cfg_valid),
    .i_cfg_ready(cfg_ready),
    .i_cfg(cfg),
    .i_tile_valid(tile_valid),
    .i_tile_ready(tile_ready),
    .i_tile_admission_ready(tile_admission_ready),
    .i_tile_rows(tile_rows),
    .i_tile_cols(tile_cols),
    .i_wr_valid(wr_valid),
    .i_wr_ready(wr_ready),
    .o_wr_data(wr_data),
    .o_wr_mask(wr_mask),
    .i_wr_last(wr_last),
    .i_state(state),
    .i_word_output_q(word_output_q),
    .i_c(c),
    .i_tile_rows_in_range(tile_rows_in_range),
    .i_tile_q_before_end(tile_q_before_end),
    .i_last_group_channel_q(last_group_channel_q),
    .o_group_range_channel(group_range_channel),
    .o_initial_group_remaining(initial_group_remaining),
    .i_window_group_remaining_q(window_group_remaining_q),
    .o_group_range_next(group_range_next),
    .i_q0(q0),
    .o_cfg_next_group(cfg_next_group),
    .o_cfg_skip_group(cfg_skip_group),
    .i_col_idx(col_idx),
    .i_cols_q(cols_q),
    .i_active_cols_q(active_cols_q),
    .i_row_last_q(row_last_q),
    .i_past_active_q(past_active_q),
    .i_narrow_output(narrow_output),
    .o_chunk_lane_allowed(chunk_lane_allowed),
    .o_chunk_selected(chunk_selected),
    .o_chunk_reaches_end(chunk_reaches_end),
    .o_ch_q(ch_q),
    .i_ch0_q(ch0_q),
    .i_ch0(ch0),
    .i_q_current(q_current),
    .i_channel_addr(channel_addr),
    .i_pad_q(pad_q),
    .o_addr(addr),
    .i_word_buf(word_buf),
    .i_word_addr(word_addr),
    .i_word_valid(word_valid),
    .o_current_word_hit(current_word_hit),
    .o_chunk_count(chunk_count),
    .i_decode_index(decode_index),
    .i_decode_inner(decode_inner),
    .i_cache_req_ready(cache_req_ready),
    .i_cache_rsp_valid(cache_rsp_valid),
    .i_cache_rsp_error(cache_rsp_failure),
    .o_cache_req_valid(cache_req_valid),
    .o_cache_rsp_ready(cache_rsp_ready),
    .o_stream_next_request(stream_next_request),
    .o_next_row_request(next_row_request),
    .o_request_stream_context(request_stream_context),
    .o_request_row_context(request_row_context),
    .o_request_tap_context(request_tap_context),
    .o_active_after_chunk(active_after_chunk),
    .i_byte_offset_sum(byte_offset_sum),
    .o_incoming_context(incoming_context),
    .o_incoming_word_hit(incoming_word_hit),
    .i_descriptor_response_forward(descriptor_response_forward),
    .i_incoming_next_tile_fast(incoming_next_tile_fast),
    .i_incoming_next_position_fast(incoming_next_position_fast),
    .i_incoming_skip_tap(incoming_skip_tap),
    .i_window_next_ch(window_next_ch),
    .o_incoming_tile_group_fits(incoming_tile_group_fits),
    .o_cache_req_addr(cache_req_addr_reference),
    .o_stream_request_addr(stream_request_addr),
    .i_cache_rsp_data(cache_rsp_data),
    .i_pred_cfg_busy(pred_cfg_busy),
    .i_cache_cfg_pending(cache_cfg_pending),
    .o_cache_config_valid(cache_config_valid),
    .i_pred_cfg_pending(pred_cfg_pending),
    .i_geometry_tile(geometry_tile),
    .i_incoming_fast(incoming_fast),
    .i_incoming_padding(incoming_padding),
    .o_incoming_tap_wrap(incoming_tap_wrap),
    .i_incoming_addr(incoming_addr),
    .i_incoming_address_candidates(incoming_address_candidates),
    .i_current_q_remainder(current_q_remainder),
    .i_next_word_o_equal(next_word_o_equal),
    .i_incoming_word_o_equal(incoming_word_o_equal),
    .i_incoming_live_word_o_equal(incoming_live_word_o_equal),
    .i_row_base_valid(row_base_valid),
    .i_coordinate_address_valid(coordinate_address_valid),
    .i_row_coordinate_valid(row_coordinate_valid),
    .i_next_row_padding(next_row_padding),
    .i_next_tap_padding(next_tap_padding),
    .i_incoming_tap_wrap_q(incoming_tap_wrap_q),
    .i_next_row_addr(next_row_addr),
    .i_next_tap_addr(next_tap_addr),
    .o_next_q_current(next_q_current),
    .i_channel_accept_fire(channel_accept_fire),
    .i_committing_tile_packed(committing_tile),
    .i_tile_commit(tile_commit),
    .i_committing_saved_word_hit(committing_saved_word_hit),
    .i_committing_live_word_hit(committing_live_word_hit),
    .i_next_row_word_match(next_row_word_match),
    .i_incoming_advanced_word_match(incoming_advanced_word_match),
    .i_group_shape_o_valid(group_shape_o_valid),
    .o_group_end_o_equal(group_end_o_equal),
    .o_stream_advance_state(stream_advance_state)
  );

  conv_im2col_prefetch #(
    .p_size(SIZE), .p_line_bytes(LINE_BYTES), .p_register_cache_request(REGISTER_CACHE_REQUEST), .p_rw(RW)
  ) u_prefetch (
    .i_clk(clk),
    .i_rst_n(rst_n),
    .i_cfg_valid(cfg_valid),
    .i_cfg_ready(cfg_ready),
    .i_tile_rows(tile_rows),
    .i_tile_cols(tile_cols),
    .i_c(c),
    .i_rows_q(rows_q),
    .i_cols_q(cols_q),
    .i_ky_q(ky_q),
    .i_ky0_q(ky0_q),
    .i_ox(ox),
    .i_oy(oy),
    .i_kx(kx),
    .i_ch(ch),
    .i_kx0(kx0),
    .i_ch0(ch0),
    .i_ix(ix),
    .i_iy(iy),
    .i_request_stream_context(request_stream_context),
    .i_request_row_context(request_row_context),
    .i_incoming_context(incoming_context),
    .i_incoming_next_tile_fast(incoming_next_tile_fast),
    .i_incoming_next_position_fast(incoming_next_position_fast),
    .i_window_next_x(window_next_x),
    .i_cache_port_valid(cache_port_valid),
    .i_cache_req_addr(cache_req_addr),
    .i_cache_port_ready(cache_port_ready),
    .i_request_addr_q(request_addr_q),
    .i_request_index_q(request_index_q),
    .i_request_epoch_q(request_epoch_q),
    .i_short_pixel_q(short_pixel_q),
    .i_retire_last_row_q(retire_last_row_q),
    .i_second_last_row_q(second_last_row_q),
    .i_last_output_col_q(last_output_col_q),
    .i_second_last_col_q(second_last_col_q),
    .i_request_index_valid_q(request_index_valid_q),
    .i_incoming_ch(incoming_ch),
    .i_incoming_ky(incoming_ky),
    .i_incoming_kx(incoming_kx),
    .i_incoming_ix(incoming_ix),
    .i_req_index(req_index),
    .i_req_epoch(req_epoch),
    .i_retirement_result(retirement_result),
    .i_req_index_valid(req_index_valid),
    .i_window_index_shift_q(window_index_shift_q),
    .o_pf_valid(pf_valid),
    .o_pf_addr(pf_addr),
    .o_pf_index(pf_index),
    .o_pf_epoch(pf_epoch),
    .o_pf_index_valid(pf_index_valid),
    .o_prefetch_phase(prefetch_phase),
    .o_pf_address_term(pf_address_term),
    .o_pfa_y(pfa_y),
    .o_pfa_channel(pfa_channel),
    .o_pf0_x(pf0_x),
    .o_pf0_y(pf0_y),
    .o_pf1_pixel(pf1_pixel),
    .o_pf1_channel(pf1_channel),
    .o_pf1_retire(pf1_retire),
    .o_pf1_ref_addr(pf1_ref_addr),
    .o_pf1_ref_index(pf1_ref_index),
    .o_pf1_ref_epoch(pf1_ref_epoch),
    .o_pf1_ref_retire(pf1_ref_retire),
    .o_pf1_ref_index_valid(pf1_ref_index_valid),
    .o_pf1_fragment(pf1_fragment),
    .o_pf1_coordinate_valid(pf1_coordinate_valid),
    .i_pf_step_base(pf_step_base),
    .i_fragment_image_fits(fragment_image_fits),
    .i_request_y(request_y),
    .i_request_output_y(request_output_y),
    .i_epoch_o_sum(epoch_o_sum),
    .i_stream_channel_full(stream_channel_full),
    .i_row_pair_dx(row_pair_dx),
    .i_row_wrap_dx(row_wrap_dx),
    .i_tap_wrap_dx(tap_wrap_dx),
    .i_row_wrap(row_wrap),
    .i_next_row_ix(next_row_ix),
    .i_prefetch_address_sum(prefetch_address_sum),
    .i_prefetch_byte_offset(prefetch_byte_offset),
    .i_prefetch_pixel_sum(prefetch_pixel_sum),
    .i_shared_channel_product(shared_channel_product)
  );
  // 行末的数据来源提前选择，填充和保存字命中只控制实际请求资格。
  assign request_row_metadata_context = !REGISTER_ROW_ADDRESS &&
      (request_stream_context || state[$clog2(ZERO_STREAM)]) &&
      chunk_reaches_end && !row_last_q && row_base_valid && !geometry_tile;
  assign request_descriptor_metadata_context = !REGISTER_DESCRIPTOR && descriptor_payload_context;
  assign request_address_reference = request_row_metadata_context ? next_row_addr : cache_req_addr_reference;

  // 描述符地址与运行位置地址共用末级归并，选择条件分别准备。
  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_address
    logic [4:0] cache_select, request_select;
    logic [13:0] cache_candidate_select, request_candidate_select;
    logic [13:0][31:0] address_candidate;
    logic [31:0] cache_address_selected, request_address_selected;
    conv_im2col_address_sources u_sources (
      .i_tap(request_tap_context), .i_incoming(incoming_context),
      .i_row(request_row_context), .i_stream(request_stream_context),
      .i_row_metadata(request_row_metadata_context),
      .o_cache(cache_select), .o_saved(request_select)
    );
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming
      assign address_candidate[candidate] = incoming_address_candidates[candidate];
      assign cache_candidate_select[candidate] = cache_select[0] && incoming_pixel_select[candidate];
      assign request_candidate_select[candidate] = request_select[0] && incoming_pixel_select[candidate];
    end
    assign address_candidate[13:10] = {addr, stream_request_addr, next_row_addr, next_tap_addr};
    assign cache_candidate_select[13:10] = cache_select[4:1];
    assign request_candidate_select[13:10] = request_select[4:1];
    onehot_mux #(.p_choices(14), .p_width(32)) u_cache_address (
      .i_select(cache_candidate_select), .i_data(address_candidate), .o_data(cache_address_selected)
    );
    onehot_mux #(.p_choices(14), .p_width(32)) u_saved_address (
      .i_select(request_candidate_select), .i_data(address_candidate), .o_data(request_address_selected)
    );
    always_comb begin
      cache_req_addr = cache_req_addr_reference;
      request_address_value = request_address_reference;
      // 未知输入继续使用条件选择的逐位合并语义。
      case (^{request_tap_context, incoming_context, request_row_context, request_stream_context,
               request_row_metadata_context, incoming_pixel_select, incoming_address_candidates,
               incoming_addr, next_tap_addr, next_row_addr, stream_request_addr, addr})
        1'b0, 1'b1: begin
          cache_req_addr = cache_address_selected;
          request_address_value = request_address_selected;
        end
        default: begin end
      endcase
    end
  end else begin : g_saved_descriptor_address
    assign cache_req_addr = cache_req_addr_reference;
    assign request_address_value = request_address_reference;
  end

  // 像素坐标先完成来源选择，再共用缓存索引移位，描述符接收周期保持不变。
  if (!REGISTER_DESCRIPTOR) begin : g_parallel_request_index
    logic [31:0] incoming_pixel_selected, request_pixel_selected;
    logic [12:0] request_select;
    logic [12:0][COORD_W+31:0] request_candidate;
    logic [31:0] incoming_index_shifted, request_index_shifted;
    onehot_mux #(.p_choices(10), .p_width(32)) u_select (
      .i_select(incoming_pixel_select), .i_data(incoming_pixel_candidates),
      .o_data(incoming_pixel_selected)
    );
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_candidate
      assign request_select[candidate] = incoming_pixel_select[candidate];
      assign request_candidate[candidate] =
        {incoming_y_candidates[candidate], incoming_pixel_candidates[candidate]} &
        {(COORD_W+32){request_descriptor_metadata_context}};
    end
    assign request_select[10] = !request_descriptor_metadata_context && request_row_metadata_context;
    assign request_select[11] = !request_descriptor_metadata_context && !request_row_metadata_context &&
      request_tap_context;
    assign request_select[12] = !request_descriptor_metadata_context && !request_row_metadata_context &&
      !request_tap_context;
    assign request_candidate[10] = {next_row_iy, next_row_pixel};
    assign request_candidate[11] = {next_tap_iy, next_tap_pixel};
    assign request_candidate[12] = {iy, pixel_index};
    onehot_mux #(.p_choices(13), .p_width(COORD_W+32)) u_request_select (
      .i_select(request_select), .i_data(request_candidate),
      .o_data({request_y_selected, request_pixel_selected})
    );
    assign incoming_index_shifted = short_pixel_q ?
      incoming_pixel_selected >> window_index_shift_q : incoming_pixel_selected;
    assign request_index_shifted = short_pixel_q ?
      request_pixel_selected >> window_index_shift_q : request_pixel_selected;
    always_comb begin
      incoming_req_index = incoming_index_shifted;
      request_index_selected = request_index_shifted;
`ifndef SYNTHESIS
      // 含未知值的移位和按位选择保留各候选独立求值的四态传播。
      if ((^{short_pixel_q, window_index_shift_q, incoming_pixel_select,
              incoming_pixel_candidates, request_select, request_candidate}) === 1'bx) begin
        incoming_req_index = '0;
        request_index_selected = '0;
        for (int candidate = 0; candidate < 10; candidate++) begin
          incoming_req_index |= (short_pixel_q ?
            incoming_pixel_candidates[candidate] >> window_index_shift_q :
            incoming_pixel_candidates[candidate]) & {32{incoming_pixel_select[candidate]}};
          request_index_selected |= (short_pixel_q ?
            incoming_pixel_candidates[candidate] >> window_index_shift_q :
            incoming_pixel_candidates[candidate]) &
            {32{incoming_pixel_select[candidate] & request_descriptor_metadata_context}};
        end
        request_index_selected |= (short_pixel_q ? next_row_pixel >> window_index_shift_q :
          next_row_pixel) & {32{request_select[10]}};
        request_index_selected |= (short_pixel_q ? next_tap_pixel >> window_index_shift_q :
          next_tap_pixel) & {32{request_select[11]}};
        request_index_selected |= current_req_index & {32{request_select[12]}};
      end
`endif
    end
  end else begin : g_registered_request_index
    logic [2:0] request_select;
    logic [2:0][COORD_W+31:0] request_candidate;
    assign incoming_req_index = short_pixel_q ? incoming_pixel >> window_index_shift_q : incoming_pixel;
    assign request_select[0] = request_row_metadata_context;
    assign request_select[1] = !request_row_metadata_context && request_tap_context;
    assign request_select[2] = !request_row_metadata_context && !request_tap_context;
    assign request_candidate[0] = {next_row_iy,
      short_pixel_q ? next_row_pixel >> window_index_shift_q : next_row_pixel};
    assign request_candidate[1] = {next_tap_iy,
      short_pixel_q ? next_tap_pixel >> window_index_shift_q : next_tap_pixel};
    assign request_candidate[2] = {iy, current_req_index};
    onehot_mux #(.p_choices(3), .p_width(COORD_W+32)) u_request_select (
      .i_select(request_select), .i_data(request_candidate),
      .o_data({request_y_selected, request_index_selected})
    );
  end
  // 两个描述符纪元独立计算格式和行内偏移，窗口匹配只选择最终结果。
  for (genvar candidate = 0; candidate < 2; candidate++) begin : g_incoming_request_epoch
    assign incoming_epoch_candidate[candidate] = short_pixel_q ? 32'd0 :
      (epoch_o_sum[candidate] << c.input_s16) >> $clog2(LINE_BYTES);
  end
  assign incoming_req_epoch = incoming_next_position_fast ? incoming_epoch_candidate[0] : incoming_epoch_candidate[1];

  // 各来源的纪元先完成格式变换，互斥选择只归并完整结果。
  if (1) begin : g_request_epoch
    logic [4:0] epoch_select;
    logic [4:0][31:0] epoch_candidate;
    assign epoch_select[0] = request_descriptor_metadata_context;
    assign epoch_select[1] = !request_descriptor_metadata_context && request_row_metadata_context;
    assign epoch_select[2] = !request_descriptor_metadata_context && !request_row_metadata_context &&
        request_tap_context;
    assign epoch_select[3] = !request_descriptor_metadata_context && !request_row_metadata_context &&
        !request_tap_context && request_stream_context;
    assign epoch_select[4] = !request_descriptor_metadata_context && !request_row_metadata_context &&
        !request_tap_context && !request_stream_context;
    assign epoch_candidate[0] = incoming_req_epoch;
    assign epoch_candidate[1] = short_pixel_q ? 32'd0 :
        (epoch_o_sum[1] << c.input_s16) >> $clog2(LINE_BYTES);
    assign epoch_candidate[2] = short_pixel_q ? 32'd0 :
        ({16'd0, c.group_offset} << c.input_s16) >> $clog2(LINE_BYTES);
    assign epoch_candidate[3] = short_pixel_q ? 32'd0 :
        (epoch_o_sum[3] << c.input_s16) >> $clog2(LINE_BYTES);
    assign epoch_candidate[4] = current_req_epoch;
    onehot_mux #(.p_choices(5), .p_width(32)) u_select (
      .i_select(epoch_select), .i_data(epoch_candidate), .o_data(request_epoch_selected)
    );
  end

  // 换核位置的元数据与下一地址共用静态上下文选择。
  always_comb begin
    request_y=request_descriptor_metadata_context ? incoming_iy : request_row_metadata_context ? next_row_iy :
      request_tap_context ? next_tap_iy : iy;
    request_output_y=request_descriptor_metadata_context ?
      (incoming_next_position_fast ? {16'd0, window_next_y} :
       incoming_next_tile_fast ? (row_wrap ? oy+32'd1 : oy) : oy) :
      request_row_metadata_context && row_wrap ? oy+32'd1 : oy;
    req_index_valid=window_index_valid_q;
    req_index=request_descriptor_metadata_context ? incoming_req_index : request_row_metadata_context ?
      (short_pixel_q ? next_row_pixel>>window_index_shift_q : next_row_pixel) :
      request_tap_context ? (short_pixel_q ? next_tap_pixel>>window_index_shift_q : next_tap_pixel) :
      current_req_index;
    req_epoch=request_descriptor_metadata_context ? incoming_req_epoch : request_row_metadata_context ?
      (short_pixel_q ? 32'd0 : (epoch_o_sum[1]<<c.input_s16)>>$clog2(LINE_BYTES)) :
      request_tap_context ? (short_pixel_q ? 32'd0 :
        ({16'd0,c.group_offset}<<c.input_s16)>>$clog2(LINE_BYTES)) :
      request_stream_context ? (short_pixel_q ? 32'd0 :
        (epoch_o_sum[3]<<c.input_s16)>>$clog2(LINE_BYTES)) : current_req_epoch;
    // 未知输入保持条件选择的逐位合并语义。
    case (^{request_descriptor_metadata_context, request_row_metadata_context,
             request_tap_context, incoming_pixel_select, incoming_y_candidates,
             incoming_iy, next_row_iy, next_tap_iy, iy, incoming_pixel_candidates,
             incoming_pixel, short_pixel_q, window_index_shift_q,
             next_row_pixel, next_tap_pixel, current_req_index})
      1'b0, 1'b1: begin
        request_y = request_y_selected;
        req_index = request_index_selected;
      end
      default: begin end
    endcase
    case (^{request_descriptor_metadata_context, request_row_metadata_context,
             request_tap_context, request_stream_context, incoming_req_epoch,
             short_pixel_q, epoch_o_sum[1], epoch_o_sum[3], c.input_s16,
             c.group_offset, current_req_epoch})
      1'b0, 1'b1: req_epoch = request_epoch_selected;
      default: begin end
    endcase
  end

  // 缓存读取宽度随输出通道数扩展，最大读取范围限定在单个缓存行内。

  // 每个状态保存独立的一位，数据选择直接读取对应状态位。

  // 输出格式状态与主状态同时保存，运行期直接选择缓存字的通道范围。
  function automatic logic state_uses_word(input st_t next_state);
    state_uses_word = next_state[$clog2(STREAM)] || next_state[$clog2(WAIT_WORD)];
  endfunction
  // 窄读取通道保存字内有效范围，宽通道直接检查当前字节地址。

  // 四项历史数据共用一个异步读端口，有效位独立复位。

  // 配置阶段的像素步长各经过独立寄存器，完整加法结果用于自然算术推断。

  for (genvar axis = 0; axis < 2; axis++) begin : g_address_bounds
    logic [COORD_W-1:0] coordinate;
    logic [15:0] limit_value;
    logic low_less, unused_low_equal;
    assign coordinate = axis == 0 ? ix : iy;
    assign limit_value = axis == 0 ? c.input_w : c.input_h;
    unsigned_compare #(.p_width(16)) u_limit (
      .i_a(coordinate[15:0]), .i_b(limit_value),
      .o_less(low_less), .o_equal(unused_low_equal)
    );
    assign address_axis_valid[axis] = !(|coordinate[COORD_W-1:16]) && low_less;
  end
  unsigned_compare #(.p_width(33)) u_address_reduction (
    .i_a(q_current), .i_b({1'b0, reduction_len}),
    .o_less(address_reduction_valid), .o_equal(unused_address_reduction_equal)
  );
  assign address_position_valid = (&address_axis_valid) && address_reduction_valid;

  assign row_pair_dx_sum = row_wrap_dx + $signed(33'(c.stride_w));
  assign row_wrap_pixel_sum = row_y_pixels + row_wrap_dx;
  assign tap_wrap_pixel_sum = tap_y_pixels + tap_wrap_dx;

  // 输出行边界先归并，运行控制仅选择对应候选结果。
  assign row_wrap_candidate[0] = cfg.output_w != 16'd0 && cfg_output_last;
  assign row_wrap_candidate[1] = committing_tile.output_wrap;
  assign row_wrap_candidate[2] = c.output_w != 16'd0 && (16'(0) == last_output_col_q);
  assign row_wrap_candidate[3] = c.output_w != 16'd0 && row_next_o_equal;
  assign row_wrap_candidate[4] = p_fast_wrap;
  assign row_wrap_candidate[5] = c.output_w != 16'd0 && (16'(decode_inner) == last_output_col_q);

  // 核列边界并行计算，写入资格仅选择已经归并的单个位。
  assign tap_wrap_candidate[0] = cfg.kernel_w != 16'd0 && cfg_kernel_last;
  assign tap_wrap_candidate[1] = cfg.kernel_w != 16'd0 && cfg_incoming_kernel_last;
  assign tap_wrap_candidate[2] = kernel_width_valid_q && committing_tile.kernel_last;
  assign tap_wrap_candidate[3] = kernel_width_valid_q && (16'(kx0) == last_kernel_col_q);
  assign tap_wrap_candidate[4] = kernel_width_valid_q && (16'(0) == last_kernel_col_q);
  assign tap_wrap_candidate[5] = kernel_width_valid_q && tap_next_o_equal;
  assign tap_wrap_candidate[6] = kernel_width_valid_q && kernel_decode_last;
  assign tap_wrap_candidate[7] = kernel_width_valid_q && (16'(k_decode_value[1:0]) == last_kernel_col_q);
  assign tap_wrap_candidate[8] = kernel_width_valid_q && (16'(decode_inner) == last_kernel_col_q);

  // 配置接收并行检查各组状态，缓存就绪参与末级条件。

  assign cfg_idle_groups[0] = {request_pending, !state[$clog2(IDLE)], cfg_prepare_phase[2], 3'b000};
  assign cfg_idle_groups[1] = {cfg_prepare_phase[1:0], address_step_phase, prefetch_phase[1:0]};
  assign cfg_idle_groups[2] = {prefetch_phase[3:2], pred_busy, pred_cfg_busy, pred_cfg_pending, cache_cfg_pending};
  for (genvar group_index = 0; group_index < 3; group_index++) begin : g_cfg_idle_group
    assign cfg_idle_group_clear[group_index] = !(|cfg_idle_groups[group_index]);
  end
  assign cfg_ready = (&cfg_idle_group_clear) && cache_cfg_ready && !cache_hint_pending && !tile_prepared_valid;
  assign stream_response_error = state[$clog2(WAIT_WORD)] && cache_rsp_failure;
  assign stream_output_accept = wr_valid && wr_ready;
  // 描述符资格与输出接收并行计算，运行寄存器在最终边沿选择保存。
  assign stream_operation_accept = stream_output_accept && !descriptor_state_context;
  logic stream_row_coordinate_update, stream_row_data_update;
  logic stream_tap_coordinate_update, stream_tap_data_update;
  conv_im2col_stream_position u_stream_position (
    .i_chunk_end(chunk_reaches_end), .i_row_last(row_last_q),
    .i_row_base_valid(row_base_valid), .i_geometry_tile(geometry_tile),
    .i_row_coordinate_valid(row_coordinate_valid), .i_past_active(past_active_q),
    .i_active_after(active_after_chunk), .i_group_end(group_end_o_equal),
    .i_coordinate_address_valid(coordinate_address_valid),
    .o_row_coordinate(stream_row_coordinate_update), .o_row_data(stream_row_data_update),
    .o_tap_coordinate(stream_tap_coordinate_update), .o_tap_data(stream_tap_data_update)
  );
  logic error_next, tile_error_next;
  conv_im2col_error_update u_error_update (
    .i_state(state), .i_error(error), .i_configuration_complete(cfg_prepare_phase == 4),
    .i_configuration_ok(cfg_ok), .i_cfg_fire(cfg_valid && cfg_ready),
    .i_basic_valid(cfg_basic_valid), .i_tile_commit(tile_commit),
    .i_tile_invalid(committing_tile.invalid), .i_stream_error(stream_response_error),
    .i_stream_accept(stream_operation_accept),
    .o_error(error_next), .o_tile_error(tile_error_next)
  );
  assign finishing_tile=stream_output_accept && wr_last;
  // 描述符在返回阶段选择当前缓存字，描述符接收条件控制保存。
  assign descriptor_response_forward = state[$clog2(WAIT_WORD)];
  // 描述符就绪的静态条件共用，配置有效只参与最终接收选择。
  assign tile_ready_static = cfg_prepare_phase==0 && configured && !error &&
                              !pred_busy && !pred_cfg_busy && !pred_cfg_pending && !cache_cfg_pending &&
                              !cache_hint_pending && address_step_phase==0;
  assign tile_admission_ready = tile_ready_static && !cfg_valid;
  conv_im2col_tile_context u_tile_context (
    .i_static_ready(tile_ready_static), .i_idle(state[$clog2(IDLE)]),
    .i_stream(state[$clog2(STREAM)]), .i_zero_stream(state[$clog2(ZERO_STREAM)]),
    .i_wait_word(state[$clog2(WAIT_WORD)]), .i_write_ready(wr_ready),
    .i_row_last(row_last_q), .i_chunk_end(chunk_reaches_end), .o_ready(tile_context_ready)
  );
  // 返回成功只合并已经准备的描述符接收资格。
  assign tile_ready_context = tile_context_ready[0] ||
      (cache_rsp_success && tile_context_ready[1]);
  assign tile_ready = tile_ready_context && !cfg_valid &&
      (!REGISTER_DESCRIPTOR || !tile_prepared_valid || tile_commit);
  assign busy = !cfg_ready;
  assign wr_valid = state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)] ||
                    (state[$clog2(WAIT_WORD)] && cache_rsp_success);
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);
  // 行末标志与行号同时保存，当前传输完成只合并列末判断。
  assign {unused_row_index_carry, next_row_idx} = {1'b0, row_idx} + (TILE_COUNT_W+1)'(1);
  assign next_row_last = 32'(next_row_idx) + 32'd1 == 32'(rows_q);
  assign wr_last = row_last_q && chunk_reaches_end;

  assign pred_start = state[$clog2(ADDRESS)] && geometry_tile && col_idx==0 &&
    address_position_valid &&
    !pred_busy && !cache_hint_pending;
  generate if (SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0) begin : g_next_use
    logic [31:0] predictor_cfg_r, predictor_position, group_q;
    // 预测器专用配置和分组状态与实例使用相同的参数条件。
    always_ff @(posedge clk) begin
      if (cfg_valid && cfg_ready) predictor_cfg_r <= cfg_sched_r;
    end
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) group_q <= 32'd0;
      else if (cfg_valid && cfg_ready) begin
      end else if (tile_commit) begin
        if (committing_tile.invalid) begin
        end else group_q <= committing_tile.group_index;
      end
    end
  // 预测器的位置输入提前按四位分组进位，后续可直接执行分块移位。
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_predictor_position (
    .i_a(p0), .i_b(32'(row_idx)), .i_carry(1'b0),
    .o_sum(predictor_position), .o_carry(unused_predictor_position_carry)
  );
    conv_next_use_predictor u_predictor (
      .clk,.rst_n,.cfg_valid(pred_cfg_pending),.cfg(c),
      .cfg_r(predictor_cfg_r),.cfg_groups(groups_q),
      .cfg_eligible(pred_cfg_eligible),.cfg_busy(pred_cfg_busy),.enabled(pred_enabled),.start(pred_start),
      .input_y(32'(iy)),.input_x(32'(ix)),.channel(ch),
      .current_p(predictor_position),.current_q(32'(q_current)),.current_group(group_q),
      .busy(pred_busy),.done(pred_done),.next_rank(pred_rank)
    );
  end else begin : g_no_next_use
    assign pred_cfg_eligible=0;assign pred_cfg_busy=0;assign pred_enabled=0;assign pred_busy=0;
    assign pred_done=0;assign pred_rank=32'hffff_ffff;
  end endgenerate

  assign byte_offset_sum={2'b0,addr[p_word_shift-1:0]}+((p_word_shift+2)'(chunk_count)<<c.input_s16);
  // 配置触发位在接收后保存；预测器生成可用标志后开始配置缓存。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pred_cfg_pending<=1'b0;
    else if (cfg_prepare_phase==4)
      pred_cfg_pending<=cfg_ok && SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0;
    else pred_cfg_pending<=1'b0;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cache_cfg_pending <= 1'b0;
    else if (cfg_valid && cfg_ready) cache_cfg_pending <= 1'b0;
    else if (cfg_prepare_phase==4) cache_cfg_pending <= cfg_ok;
    else if (cache_config_valid && cache_cfg_ready) cache_cfg_pending <= 1'b0;
  end
  // 卷积核列数据按运行阶段预选，各保存条件仅控制寄存器写入。
  always_comb begin
    kernel_column_reference = 16'(kx + 1);
    if (tap_wrap) kernel_column_reference = 16'd0;
    if (chunk_reaches_end) kernel_column_reference = 16'(kx0);
    if (state[$clog2(K_DECODE)]) begin
      kernel_column_reference = 16'(k_decode_value[1:0]);
      if (kernel_shape_o_valid) kernel_column_reference = kernel_decode_column;
    end
    if (state[$clog2(K_WAIT)]) kernel_column_reference = 16'(decode_inner);
    if (descriptor_payload_context) kernel_column_reference = 16'(committing_tile.kernel_x);
  end

  // 数据来源由运行阶段提前选择，描述符和输出接收只决定保存时刻。
  assign descriptor_payload_context = state[$clog2(IDLE)] ||
      ((state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) && wr_last);
  always_comb begin
    coordinate_payload[0] = next_tap_ix;
    coordinate_payload[1] = next_tap_iy;
    pixel_payload = next_tap_pixel;
    tap_group_reference = next_tap_addr;
    row_group_reference = next_row_group_base;
    if (chunk_reaches_end) begin
      coordinate_payload[0] = next_row_ix;
      coordinate_payload[1] = next_row_iy;
      pixel_payload = next_row_pixel;
      tap_group_reference = next_row_group_base;
    end
    if (state[$clog2(COORD_PAD)]) begin
      coordinate_payload[0] = coordinate_padded_x;
      coordinate_payload[1] = coordinate_padded_y;
    end
    if (state[$clog2(ADDRESS_PIXEL)]) pixel_payload = pixel_product + 32'(ix);
    if (state[$clog2(ADDRESS_CHANNEL)]) begin
      tap_group_reference = group_base_addr;
      row_group_reference = group_base_addr;
    end
    if (descriptor_payload_context) begin
      coordinate_payload[0] = committing_tile.input_x;
      coordinate_payload[1] = committing_tile.input_y;
      pixel_payload = committing_tile.pixel;
      tap_group_reference = committing_tile.group_address;
      row_group_reference = committing_tile.group_address;
    end
  end

  if (!REGISTER_DESCRIPTOR) begin : g_parallel_descriptor_payload
    logic [13:0] kernel_select;
    logic [13:0][15:0] kernel_candidate;
    logic [15:0] kernel_selected, decoded_kernel_column;
    logic [12:0] group_select;
    logic [12:0][63:0] group_candidate;
    logic [63:0] group_selected;

    // 描述符和运行来源组成同一组候选，接收资格仅控制已有寄存器的写入。
    for (genvar candidate = 0; candidate < 10; candidate++) begin : g_incoming
      assign kernel_select[candidate] = descriptor_payload_context && incoming_pixel_select[candidate];
      assign kernel_candidate[candidate] = incoming_kernel_x_candidates[candidate];
      assign group_select[candidate] = descriptor_payload_context && incoming_pixel_select[candidate];
      assign group_candidate[candidate] = {2{incoming_group_candidates[candidate]}};
    end
    assign kernel_select[10] = !descriptor_payload_context && state[$clog2(K_WAIT)];
    assign kernel_select[11] = !descriptor_payload_context && !state[$clog2(K_WAIT)] && state[$clog2(K_DECODE)];
    assign kernel_select[12] = !descriptor_payload_context && !state[$clog2(K_WAIT)] &&
        !state[$clog2(K_DECODE)] && chunk_reaches_end;
    assign kernel_select[13] = !descriptor_payload_context && !state[$clog2(K_WAIT)] &&
        !state[$clog2(K_DECODE)] && !chunk_reaches_end;
    assign decoded_kernel_column = kernel_shape_o_valid ? kernel_decode_column : 16'(k_decode_value[1:0]);
    assign kernel_candidate[10] = 16'(decode_inner);
    assign kernel_candidate[11] = decoded_kernel_column;
    assign kernel_candidate[12] = 16'(kx0);
    assign kernel_candidate[13] = tap_wrap ? 16'd0 : 16'(kx + 1);
    onehot_mux #(.p_choices(14), .p_width(16)) u_kernel (
      .i_select(kernel_select), .i_data(kernel_candidate), .o_data(kernel_selected)
    );
    assign group_select[10] = !descriptor_payload_context && state[$clog2(ADDRESS_CHANNEL)];
    assign group_select[11] = !descriptor_payload_context && !state[$clog2(ADDRESS_CHANNEL)] && chunk_reaches_end;
    assign group_select[12] = !descriptor_payload_context && !state[$clog2(ADDRESS_CHANNEL)] && !chunk_reaches_end;
    assign group_candidate[10] = {group_base_addr, group_base_addr};
    assign group_candidate[11] = {next_row_group_base, next_row_group_base};
    assign group_candidate[12] = {next_row_group_base, next_tap_addr};
    onehot_mux #(.p_choices(13), .p_width(64)) u_group (
      .i_select(group_select), .i_data(group_candidate), .o_data(group_selected)
    );
`ifdef SYNTHESIS
    assign kernel_column_payload = kernel_selected;
    assign {row_group_payload, tap_group_payload} = group_selected;
`else
    // 未知控制或数据保留逐阶段赋值的四态传播。
    always_comb begin
      kernel_column_payload = kernel_column_reference;
      row_group_payload = row_group_reference;
      tap_group_payload = tap_group_reference;
      case (^{descriptor_payload_context, incoming_pixel_select, incoming_kernel_x_candidates,
              incoming_group_candidates, state, chunk_reaches_end, kernel_shape_o_valid,
              kernel_decode_column, k_decode_value, decode_inner, kx0, kx, tap_wrap,
              group_base_addr, next_row_group_base, next_tap_addr})
        1'b0, 1'b1: begin
          kernel_column_payload = kernel_selected;
          {row_group_payload, tap_group_payload} = group_selected;
        end
        default: begin end
      endcase
    end
`endif
  end else begin : g_saved_descriptor_payload
    assign kernel_column_payload = kernel_column_reference;
    assign row_group_payload = row_group_reference;
    assign tap_group_payload = tap_group_reference;
  end

  // 请求地址、窗口索引和有效位同时寄存，缓存只接收已保存的完整请求。
  // 输出接收旧请求的同一周期可保存新请求，停顿期间保持全部字段。
  assign cache_port_valid = REGISTER_CACHE_REQUEST ? request_pending : cache_req_valid;
  assign cache_req_ready = REGISTER_CACHE_REQUEST ?
      (!request_pending || cache_port_ready) : cache_port_ready;
  // 请求字段保存时同步准备读取快照，下一周期由正式请求有效位决定是否消费。
  always_comb begin
    preview_capture_valid = REGISTER_CACHE_REQUEST && cache_req_valid && cache_req_ready;
    case (cache_req_ready)
      1'b1: preview_capture_valid = REGISTER_CACHE_REQUEST;
      default: ;
    endcase
  end
  always_comb begin
    current_req_index = pixel_index;
    current_req_epoch = (epoch_o_sum[2]<<c.input_s16)>>$clog2(LINE_BYTES);
    if (short_pixel_q) begin
      current_req_index = pixel_index>>window_index_shift_q;
      current_req_epoch = 0;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) request_pending <= 1'b0;
    else if (cache_req_ready) request_pending <= REGISTER_CACHE_REQUEST && cache_req_valid;
  end
  always_ff @(posedge clk) begin
    if (!request_pending || cache_port_ready) begin
      request_addr_q <= request_address_value;
      request_geometry_q <= incoming_context ? committing_tile.geometry : geometry_tile;
      request_event_first_q <= (incoming_context ? committing_tile.geometry : geometry_tile) && cache_req_addr[3:0]==0;
      request_index_valid_q <= req_index_valid;
      request_index_q <= req_index;
      request_epoch_q <= req_epoch;
      request_y_q <= request_y[15:0];
      request_progress_q <= request_output_y;
    end
  end
  conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(p_cache_read_width),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .DEMAND_DEPTH(CACHE_RESPONSE_DEPTH),
    .p_defer_retire_shift(CACHE_POLICY == 3),
    .p_preview_request(REGISTER_CACHE_REQUEST && CACHE_RESPONSE_DEPTH == 1)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cache_config_valid),.cfg_ready(cache_cfg_ready),
    .cfg_base(c.input_base),.cfg_bytes(tensor_bytes),.cfg_bypass(c.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(c.windowed),.cfg_prefetch_enable(c.prefetch_enable),
    .req_valid(cache_port_valid),.req_ready(cache_port_ready),
    .preview_valid(preview_capture_valid),
    .preview_addr(request_address_value),
    .preview_index_valid(req_index_valid),.preview_index(req_index),
    .req_addr(REGISTER_CACHE_REQUEST ? request_addr_q : cache_req_addr),
    .req_geometry(REGISTER_CACHE_REQUEST ? request_geometry_q : geometry_tile),
    .req_event_first(REGISTER_CACHE_REQUEST ? request_event_first_q :
      (geometry_tile && cache_req_addr[3:0] == 4'd0)),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .req_window_index_valid(REGISTER_CACHE_REQUEST ? request_index_valid_q : req_index_valid),
    .req_window_index(REGISTER_CACHE_REQUEST ? request_index_q : req_index),
    .req_window_epoch(REGISTER_CACHE_REQUEST ? request_epoch_q : req_epoch),
    .req_window_retire(request_retire),
    .req_window_progress(REGISTER_CACHE_REQUEST ? request_progress_q : request_output_y),
    .prefetch_valid(pf_valid),.prefetch_ready(unused_pf_ready),.prefetch_addr(pf_addr),
    .prefetch_window_index_valid(pf_index_valid),.prefetch_window_index(pf_index),
    .prefetch_window_epoch(pf_epoch),.prefetch_window_retire(
      (!pf1_coordinate_valid && pf1_fragment) ? pf1_ref_retire : pf1_retire),
    .prefetch_next_fragment(pf1_fragment),
    .prefetch_ref_valid(1'b1),.prefetch_ref_addr(pf1_ref_addr),
    .prefetch_ref_index_valid(pf1_ref_index_valid),.prefetch_ref_index(pf1_ref_index),
    .prefetch_ref_epoch(pf1_ref_epoch),
    .rsp_valid(cache_rsp_valid),.rsp_ready(cache_rsp_ready),
    .rsp_data(cache_rsp_data),.rsp_error(unused_cache_rsp_error),
    .rsp_success(cache_rsp_success),.rsp_failure(cache_rsp_failure),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
  );
  // 解码递增与配置边界的完整结果分别连接已有保存边沿。

  assign decode_index_advance = decode_index + 1;
  assign decode_inner_advance = decode_inner + 1;
  assign position_high_minus_one = cfg_positions[31:p_row_low_w] - p_row_high_w'(1);

  // 输出资格由保存的运行状态确定。
  assign word_output_q = state_uses_word(state);

  // 描述符数据在当前传输完成前形成候选状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state <= IDLE;
    end else if (state_update) begin
      state <= selected_state;
    end
  end

  assign descriptor_commit_eligible = REGISTER_DESCRIPTOR ? tile_prepared_valid && !error :
      tile_valid && tile_admission_ready;
  assign descriptor_state_context = descriptor_commit_eligible &&
      (state[$clog2(IDLE)] ||
       ((state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) && wr_last));

  // 描述符字段提前决定候选状态，接收事件控制保存。
  conv_im2col_descriptor_state #(.p_register_descriptor(REGISTER_DESCRIPTOR)) u_descriptor_state (
    .i_invalid(committing_tile.invalid), .i_fast(committing_tile.fast),
    .i_padding(committing_tile.padding), .i_word_hit(committing_tile.word_hit),
    .i_cache_req_ready(cache_req_ready), .o_state(descriptor_state)
  );

  // 当前操作和准备好的地址结果并行形成运行状态。
  always_comb begin
    operation_state = state;
    unique case (1'b1)
      state[$clog2(DESCRIPTOR_CHECK)]: begin
        if (descriptor_padding) operation_state = ZERO_STREAM;
        else if (committing_saved_word_hit || committing_live_word_hit) operation_state = STREAM;
        else operation_state = FETCH;
      end
      (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]):
        operation_state = stream_advance_state;
      state[$clog2(P_HISTORY)]: operation_state = P_DECODE;
      state[$clog2(P_DECODE)]: begin
        if (p_fast_valid) operation_state = Q_DECODE;
        else operation_state = P_START;
      end
      state[$clog2(P_START)]: operation_state = P_WAIT;
      state[$clog2(P_WAIT)]: operation_state = Q_DECODE;
      state[$clog2(Q_DECODE)]: begin
        if (q0==0 || group_shape_o_valid || (c.group_c==3 && q0<27)) operation_state = K_DECODE;
        else operation_state = Q_START;
      end
      state[$clog2(Q_START)]: operation_state = Q_WAIT;
      state[$clog2(Q_WAIT)]: operation_state = K_DECODE;
      state[$clog2(K_DECODE)]: begin
        if (kernel_shape_o_valid || (c.kernel_w==3 && tap0<9)) operation_state = COORD;
        else operation_state = K_START;
      end
      state[$clog2(K_START)]: operation_state = K_WAIT;
      state[$clog2(K_WAIT)]: operation_state = COORD;
      state[$clog2(COORD)]: operation_state = COORD_SUM;
      state[$clog2(COORD_SUM)]: operation_state = COORD_BORROW;
      state[$clog2(COORD_BORROW)]: operation_state = COORD_PAD;
      state[$clog2(COORD_PAD)]: operation_state = ADDRESS;
      state[$clog2(ADDRESS)]: begin
        if (!address_position_valid) operation_state = ZERO_STREAM;
        else operation_state = ADDRESS_PIXEL;
      end
      state[$clog2(ADDRESS_PIXEL)]: operation_state = ADDRESS_PRODUCT;
      state[$clog2(ADDRESS_PRODUCT)]: operation_state = ADDRESS_MERGE;
      state[$clog2(ADDRESS_MERGE)]: operation_state = ADDRESS_BASE;
      state[$clog2(ADDRESS_BASE)]: operation_state = ADDRESS_CHANNEL;
      state[$clog2(ADDRESS_CHANNEL)]: operation_state = ADDRESS_MATCH;
      state[$clog2(ADDRESS_MATCH)]: begin
        if (!address_position_valid) operation_state = ZERO_STREAM;
        else operation_state = FETCH;
      end
      state[$clog2(FETCH)]: begin
        if (current_word_hit) operation_state = STREAM;
        else operation_state = WAIT_WORD;
      end
      state[$clog2(IDLE)]: ;
      default: operation_state = IDLE;
    endcase
  end

  // 返回响应决定保存时刻，错误返回优先选择空闲状态。
  always_comb begin
    selected_state = operation_state;
    if (descriptor_state_context) selected_state = descriptor_state;
    if (state[$clog2(WAIT_WORD)] && cache_rsp_failure) selected_state = IDLE;
    case (tile_commit)
      1'b0, 1'b1: ;
      default: selected_state = IDLE;
    endcase
  end
  always_comb begin
    state_update = 1'b1;
    unique case (1'b1)
      (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]): begin
        state_update = 1'b0;
        if (stream_response_error) state_update = 1'b1;
        else if (stream_output_accept) state_update = 1'b1;
      end
      state[$clog2(P_WAIT)]: state_update = decode_index == p0;
      state[$clog2(Q_WAIT)]: state_update = decode_index == q0;
      state[$clog2(K_WAIT)]: state_update = decode_index == tap0;
      state[$clog2(ADDRESS)]: begin
        state_update = 1'b0;
        if (!address_position_valid) state_update = 1'b1;
        else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) state_update = 1'b1;
      end
      state[$clog2(FETCH)]: state_update = current_word_hit || cache_req_ready;
      state[$clog2(IDLE)]: state_update = descriptor_commit_eligible;
      default: ;
    endcase
    case (tile_commit)
      1'b0, 1'b1: ;
      default: state_update = 1'b1;
    endcase
    if (cfg_valid && cfg_ready) state_update = 1'b0;
  end

  // 配置与运行错误分别形成候选，接收事件只选择最终错误标志。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      error <= 1'b0;
      tile_error <= 1'b0;
    end else begin
      error <= error_next;
      tile_error <= tile_error_next;
    end
  end

  // 各运行来源先准备回绕值与写入资格，接收事件只选择完整结果。
  assign wrap_cfg_fire = cfg_valid && cfg_ready;
  assign wrap_descriptor_check = state[$clog2(DESCRIPTOR_CHECK)];
  assign wrap_running_state = state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)];
  always_comb begin
    wrap_update_candidate[0] = {3'b111, tap_wrap_candidate[1], tap_wrap_candidate[0], row_wrap_candidate[0]};
    wrap_update_candidate[1] = '0;
    if (committing_tile.invalid) begin
    end else if (committing_tile.fast) begin
      wrap_update_candidate[1][5:4] = 2'b11;
      wrap_update_candidate[1][2:1] = {2{tap_wrap_candidate[2]}};
      if (committing_tile.output_position_update) begin
        wrap_update_candidate[1][3] = 1'b1;
        wrap_update_candidate[1][0] = row_wrap_candidate[1];
      end
    end
    wrap_update_candidate[2] = '0;
    if (chunk_reaches_end) begin
      if (row_last_q) begin
      end else begin
        wrap_update_candidate[2][4:3] = 2'b11;
        wrap_update_candidate[2][1] = tap_wrap_candidate[3];
        if (row_wrap) wrap_update_candidate[2][0] = row_wrap_candidate[2];
        else wrap_update_candidate[2][0] = row_wrap_candidate[3];
      end
    end else if (past_active_q || !active_after_chunk) begin
    end else if (group_end_o_equal) begin
      wrap_update_candidate[2][4] = 1'b1;
      if (tap_wrap) wrap_update_candidate[2][1] = tap_wrap_candidate[4];
      else wrap_update_candidate[2][1] = tap_wrap_candidate[5];
    end
    wrap_update_candidate[3] = '0;
    case (1'b1)
      state[$clog2(P_HISTORY)]: ;
      state[$clog2(P_DECODE)]: if (p_fast_valid) begin
        wrap_update_candidate[3][3] = 1'b1;
        wrap_update_candidate[3][0] = row_wrap_candidate[4];
      end
      state[$clog2(P_START)]: ;
      state[$clog2(P_WAIT)]: if (decode_index == p0) begin
        wrap_update_candidate[3][3] = 1'b1;
        wrap_update_candidate[3][0] = row_wrap_candidate[5];
      end
      state[$clog2(Q_DECODE)]: ;
      state[$clog2(Q_START)]: ;
      state[$clog2(Q_WAIT)]: ;
      state[$clog2(K_DECODE)]: begin
        if (kernel_shape_o_valid) begin
          wrap_update_candidate[3][5:4] = 2'b11;
          wrap_update_candidate[3][2:1] = {2{tap_wrap_candidate[6]}};
        end else if (c.kernel_w == 16'd3 && tap0 < 32'd9) begin
          wrap_update_candidate[3][5:4] = 2'b11;
          wrap_update_candidate[3][2:1] = {2{tap_wrap_candidate[7]}};
        end
      end
      state[$clog2(K_START)]: ;
      state[$clog2(K_WAIT)]: if (decode_index == tap0) begin
        wrap_update_candidate[3][5:4] = 2'b11;
        wrap_update_candidate[3][2:1] = {2{tap_wrap_candidate[8]}};
      end
      default: ;
    endcase
  end
  conv_im2col_wrap_update_select u_wrap_update (
    .i_configuration(wrap_cfg_fire), .i_commit(tile_commit),
    .i_descriptor_check(wrap_descriptor_check), .i_stream_error(stream_response_error),
    .i_stream_accept(stream_operation_accept), .i_running(wrap_running_state),
    .i_candidate(wrap_update_candidate), .o_write(wrap_write), .o_value(wrap_value)
  );

  // 输出行和卷积核回绕标志保持原有写入边沿与配置优先级。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      row_wrap_q <= 1'b0;
      tap_wrap_q <= 1'b0;
      incoming_tap_wrap_q <= 1'b0;
    end else begin
      if (wrap_write[0]) row_wrap_q <= wrap_value[0];
      if (wrap_write[1]) tap_wrap_q <= wrap_value[1];
      if (wrap_write[2]) incoming_tap_wrap_q <= wrap_value[2];
    end
  end

  // 保存前端配置、描述符和坐标状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      c<='0; configured<=0;  tile_done<=0;
      fragment_image_fits<=0;
      reduction_len<=0; position_count<=0; tensor_bytes<=0;
      position_high_minus_one_q <= '1;
      next_group_q <= 33'd0;
      skip_group_q <= 33'd0;
      p0<=0; q0<=0; tap0<=0; row_idx<=0; col_idx<=0; rows_q<=0; cols_q<=TILE_COUNT_W'(SIZE);active_cols_q<=0;
      row_last_q <= 1'b0;
      past_active_q <= 1'b1;
      narrow_output <= 1'b0;
      ox_q <= 16'(0); oy_q <= 16'(0); ky_q <= 16'(0); kx_q <= 16'(0); ky0_q <= 16'(0); kx0_q <= 16'(0); ch0_q <= 16'(0);
      tap_group_base<=0;row_group_base<=0;
      q_current<=0; ix <= COORD_W'(0); iy <= COORD_W'(0); pixel_index <= 32'(0); pad_q<=0;
      word_buf<=0; word_addr<=0; word_valid<=0;  slot_q<=0;
      groups_q<=0;geometry_tile<=0;line_hint_valid<=0;line_hint_rank<=32'hffff_ffff;
      p_cache_valid<=0;last_p_valid<=0;last_p<=0;last_p_overflow_q<=0;last_y<=0;last_x<=0;
      address_step_phase<=0;row_wrap_dx <= 33'(0);tap_wrap_dx <= 33'(0);row_pair_dx<=0;
      row_y_pixels <= 33'(0);tap_y_pixels <= 33'(0);row_wrap_pixels <= 33'(0);tap_wrap_pixels <= 33'(0);
      row_step_bytes<=0;tap_step_bytes<=0;row_wrap_bytes<=0;tap_wrap_bytes<=0;
      row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;
      row_base_ix <= COORD_W'(0);row_base_iy <= COORD_W'(0);row_base_pixel <= 32'(0);row_base_addr<=0;
    end else begin
      tile_done<=finishing_tile;
      if (state[$clog2(WAIT_WORD)] && wr_valid && wr_ready) begin
        word_buf<=cache_rsp_data;word_addr<={addr[31:p_word_shift],{p_word_shift{1'b0}}};word_valid<=1;
      end
      if (address_step_phase==2) begin
        row_pair_dx<=row_pair_dx_sum;
        row_wrap_pixels <= row_wrap_pixel_sum;
        tap_wrap_pixels <= tap_wrap_pixel_sum;
        address_step_phase<=1;
      end else if (address_step_phase==1) begin
        address_step_phase<=3;
      end else if (address_step_phase==3) begin
        row_wrap_bytes <= shared_channel_product[0][31:0] << c.input_s16;
        tap_wrap_bytes <= shared_channel_product[1][31:0] << c.input_s16;
        address_step_phase<=0;
      end
      if (cfg_prepare_phase == 3'd1) row_y_pixels <= {1'b0, shared_coordinate_product[3]};
      if (cfg_prepare_phase == 3'd2) begin
        // 先保存无符号乘积，下一阶段计算有符号回绕位移。
        row_wrap_dx <= {1'b0, shared_coordinate_product[0]};
        tap_wrap_dx <= {1'b0, shared_coordinate_product[1]};
        tap_y_pixels <= {1'b0, shared_coordinate_product[2]};
        row_step_bytes <= shared_coordinate_product[3] << c.input_s16;
      end
      if (cfg_prepare_phase==3) begin
        row_wrap_dx <= 33'(c.stride_w) - row_wrap_dx;
        tap_wrap_dx <= 33'(c.dilation_w) - tap_wrap_dx;
        tap_step_bytes <= shared_coordinate_product[3] << c.input_s16;
        address_step_phase <= 2'd2;
      end
      if (cfg_prepare_phase==4) begin
        configured<=cfg_ok;
        reduction_len<=32'(cfg_red);position_count<=cfg_positions;tensor_bytes<=32'(cfg_input_bytes);
        // 配置边沿同时保存位置上限及其高位减一值，供低位进位时比较。
        position_high_minus_one_q <= position_high_minus_one;
        fragment_image_fits<=CACHE_WAYS>=2 &&
          cfg_input_bytes<=((64'(c.input_c)<<c.input_s16)<<$clog2(CACHE_SETS));
      end
      if (pred_done) begin line_hint_valid<=1;line_hint_rank<=pred_rank;end
      if (pred_start) line_hint_valid<=0;
      // 配置、描述符提交与各运行状态互斥选择，公共写条件只参与末级组合。
      unique case (1'b1)
        (cfg_valid && cfg_ready): begin
       c<=cfg; configured<=0;
        next_group_q <= cfg_next_group;
        skip_group_q <= cfg_skip_group;
        word_valid<=0;  reduction_len<=0;
        fragment_image_fits<=0;
        position_count<=0; tensor_bytes<=0;
        position_high_minus_one_q <= '1;
        groups_q<=cfg_sched_groups;geometry_tile<=0;line_hint_valid<=0;
        p_cache_valid<=0;last_p_valid<=0;
        address_step_phase <= 2'd0;
        row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;
        end
        tile_commit: begin
        if (committing_tile.invalid) begin
        end else begin
          p0<=committing_tile.position; q0<=committing_tile.reduction;
          q_current<={1'b0,committing_tile.reduction};
          next_group_q <= committing_tile.next_group;
          skip_group_q <= committing_tile.skip_group;
          row_last_q <= committing_tile.rows == TILE_COUNT_W'(1);
          rows_q<=committing_tile.rows; cols_q<=committing_tile.columns;
          active_cols_q <= committing_tile.active_columns;
          past_active_q <= 1'b0;
          row_idx<=0; col_idx<=0; slot_q<=committing_tile.slot;
          narrow_output <= committing_tile.narrow_output;
          row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;
          geometry_tile<=committing_tile.geometry;
          if (committing_tile.fast) begin
            tap0<=committing_tile.tap; ch0_q<=16'(committing_tile.channel);
            if (committing_tile.output_position_update) begin
              ox_q<=committing_tile.output_x; oy_q<=committing_tile.output_y;
            end
            ky_q<=16'(committing_tile.kernel_y); ky0_q<=16'(committing_tile.kernel_y);
            kx_q<=kernel_column_payload; kx0_q<=16'(committing_tile.kernel_x);
            ix <= coordinate_payload[0]; iy <= coordinate_payload[1];
            pixel_index <= pixel_payload;
            if (!REGISTER_DESCRIPTOR) pad_q<=committing_tile.padding;
            tap_group_base <= tap_group_payload; row_group_base <= row_group_payload;
            row_base_valid<=1;coordinate_address_valid<=1;row_coordinate_valid<=1;
            row_base_ix<=committing_tile.input_x; row_base_iy<=committing_tile.input_y;
            row_base_pixel<=committing_tile.pixel; row_base_addr<=committing_tile.address;
          end
        end
        end
        state[$clog2(DESCRIPTOR_CHECK)]: begin
          pad_q <= descriptor_padding;
          if (committing_saved_word_hit) begin
            word_buf <= descriptor_word_data_q;
            word_addr <= {addr[31:p_word_shift], {p_word_shift{1'b0}}};
            word_valid <= 1'b1;
          end
        end
        stream_response_error: begin
        end
        stream_operation_accept: begin
          // 行推进和内核推进分别确定字段写入资格。
          if (stream_row_coordinate_update || stream_tap_coordinate_update) begin
            ix <= coordinate_payload[0]; iy <= coordinate_payload[1];
          end
          if (stream_row_data_update || stream_tap_data_update) begin
            pixel_index <= pixel_payload;
            tap_group_base <= tap_group_payload;
          end
          if (stream_row_data_update) begin
            pad_q <= next_row_padding;
            row_group_base <= row_group_payload;
          end else if (stream_tap_data_update) pad_q <= next_tap_padding;
          if (chunk_reaches_end) begin
            if (row_last_q) begin tile_done<=1; end
            else begin
              row_idx<=next_row_idx; row_last_q<=next_row_last; col_idx<=0; q_current<={1'b0,q0};
               past_active_q <= 1'b0;
              ky_q <= 16'(ky0); kx_q <= kernel_column_payload;
              if (row_wrap) begin ox_q <= 16'(0); oy_q <= 16'(oy+1); end
              else begin
                ox_q <= 16'(ox+1);
              end
              if (row_base_valid && !geometry_tile) begin
                 coordinate_address_valid<=1;
                row_base_ix <= COORD_W'(next_row_ix);row_base_iy <= COORD_W'(next_row_iy);
                row_base_pixel <= 32'(next_row_pixel);row_base_addr<=next_row_addr;
              end else if (row_coordinate_valid) begin
                row_base_ix<=next_row_ix;row_base_iy<=next_row_iy;
                row_base_valid<=0;coordinate_address_valid<=0;
              end else begin row_base_valid<=0;end
            end
          end else begin
            col_idx<=col_idx+TILE_COUNT_W'(chunk_count); q_current<=next_q_current;
            // 填充列同样推进计数，保留原有定宽减法的回绕结果。
             // 仅在写入握手时推进；到达有效尾部后保持，直到下一行或描述符。
             past_active_q <= past_active_q || !active_after_chunk;
             if (past_active_q || !active_after_chunk) begin
             end
            else if (group_end_o_equal) begin
              if (coordinate_address_valid) begin
                if (tap_wrap) begin kx_q <= kernel_column_payload;
                ky_q <= 16'(ky+1);
                end
                else begin
                  kx_q <= kernel_column_payload;
                end
              end else begin
                if (tap_wrap) begin kx_q<=kernel_column_payload; ky_q<=16'(ky+1);end
                else begin
                  kx_q <= kernel_column_payload;
                end
                coordinate_address_valid<=0;
              end
            end
          end
        end
        (!tile_commit && stream_response_error !== 1'b1 && stream_operation_accept !== 1'b1 &&
          (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)])): ;
        state[$clog2(P_HISTORY)]: ;
        state[$clog2(P_DECODE)]: if (p_fast_valid) begin
          oy_q <= 16'(p_fast_y);ox_q <= 16'(p_fast_x);
          last_p_valid<=1;last_p<=p0;last_p_overflow_q <= (&p0[31:16]) && history_limit_carry;last_y<=16'(p_fast_y);last_x<=16'(p_fast_x);
          p_cache_valid[p_cache_select]<=1;
        end
        state[$clog2(P_START)]: ;
        state[$clog2(P_WAIT)]: if (decode_index==p0) begin
          oy_q <= 16'(decode_outer);
          ox_q <= 16'(decode_inner);
          last_p_valid<=1;last_p<=p0;last_p_overflow_q <= (&p0[31:16]) && history_limit_carry;last_y<=16'(decode_outer);last_x<=16'(decode_inner);
          p_cache_valid[p_cache_select]<=1;
        end
        state[$clog2(Q_DECODE)]: begin
          if (q0==0) begin
            tap0<=0;ch0_q <= 16'(0);
          end
          else if (group_shape_o_valid) begin
            tap0 <= q0 >> group_width_shift;
            // 通道余数与分组范围准备共用已经保存的配置掩码。
            ch0_q <= group_range_channel[2];
          end else if (c.group_c==3 && q0<27) begin
            tap0<=32'(current_q_div3);
            ch0_q <= current_q_remainder;
          end
        end
        state[$clog2(Q_START)]: ;
        state[$clog2(Q_WAIT)]: if (decode_index==q0) begin
          tap0<=decode_outer; ch0_q <= 16'(decode_inner);
        end
        state[$clog2(K_DECODE)]: begin
          if (kernel_shape_o_valid) begin
            ky_q <= 16'(tap0 >> kernel_width_shift);
            ky0_q <= 16'(tap0 >> kernel_width_shift);
            kx_q <= kernel_column_payload;
            kx0_q <= kernel_decode_column;
          end else if (c.kernel_w==3 && tap0<9) begin
            // 三列卷积核的行列由同一完整组合译码得到。
            ky_q <= 16'(k_decode_value[5:2]);
            ky0_q <= 16'(k_decode_value[5:2]);
            kx_q <= kernel_column_payload;
            kx0_q <= 16'(k_decode_value[1:0]);
          end
        end
        state[$clog2(K_START)]: ;
        state[$clog2(K_WAIT)]: if (decode_index==tap0) begin
          ky_q <= 16'(decode_outer);
          ky0_q <= 16'(decode_outer);
          kx_q <= kernel_column_payload;
          kx0_q <= 16'(decode_inner);
        end
        state[$clog2(COORD)]: begin
          coordinate_address_valid<=0;
        end
        state[$clog2(COORD_SUM)]: ;
        state[$clog2(COORD_BORROW)]: ;
        state[$clog2(COORD_PAD)]: begin
          ix <= coordinate_payload[0];
          iy <= coordinate_payload[1];
        end
        state[$clog2(ADDRESS)]: begin
          if (col_idx==0) begin
            row_coordinate_valid<=1;row_base_ix<=ix;row_base_iy<=iy;
          end
          if (!address_position_valid) begin
            pad_q<=1;
          end else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) begin
            pad_q<=0;
          end
        end
        state[$clog2(ADDRESS_PIXEL)]: begin
          pixel_index <= pixel_payload;
        end
        state[$clog2(ADDRESS_PRODUCT)]: ;
        state[$clog2(ADDRESS_MERGE)]: ;
        state[$clog2(ADDRESS_BASE)]: ;
        state[$clog2(ADDRESS_CHANNEL)]: begin
          tap_group_base <= tap_group_payload;
          coordinate_address_valid<=1;
          if (col_idx==0) begin
            row_base_valid<=1;row_base_ix<=ix;row_base_iy<=iy;row_base_pixel<=pixel_index;
            row_base_addr<=channel_addr;
            row_group_base <= row_group_payload;
          end
        end
        state[$clog2(ADDRESS_MATCH)]: begin
          pad_q <= !address_position_valid;
        end
        state[$clog2(FETCH)]: ;
        (state[$clog2(IDLE)] && !(cfg_valid && cfg_ready) && !tile_commit): ;
        default: begin configured<=0;  end
      endcase
    end
  end
  // 解码计数与坐标运算由运行状态保护，复位期间保持数据寄存器。
  always_ff @(posedge clk) begin
    if (!rst_n) begin
    end else begin
      unique case (1'b1)
        (cfg_valid && cfg_ready): ;
        tile_commit: ;
        (!tile_commit && (state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] ||
                          state[$clog2(ZERO_STREAM)])): ;
        state[$clog2(P_DECODE)]: ;
        state[$clog2(P_START)]: begin
          decode_index <= 0;
          decode_outer <= 0;
          decode_inner <= 0;
        end
        state[$clog2(P_WAIT)]: begin
          if (decode_index == p0) begin
          end else begin
            decode_index <= decode_index_advance;
            if (decode_end_o_equal[0]) begin
              decode_inner <= 0;
              decode_outer <= decode_outer + 1;
            end else decode_inner <= decode_inner_advance;
          end
        end
        state[$clog2(Q_DECODE)]: ;
        state[$clog2(Q_START)]: begin
          decode_index <= 0;
          decode_outer <= 0;
          decode_inner <= 0;
        end
        state[$clog2(Q_WAIT)]: begin
          if (decode_index == q0) begin
          end else begin
            decode_index <= decode_index_advance;
            if (decode_end_o_equal[1]) begin
              decode_inner <= 0;
              decode_outer <= decode_outer + 1;
            end else decode_inner <= decode_inner_advance;
          end
        end
        state[$clog2(K_DECODE)]: ;
        state[$clog2(K_START)]: begin
          decode_index <= 0;
          decode_outer <= 0;
          decode_inner <= 0;
        end
        state[$clog2(K_WAIT)]: begin
          if (decode_index == tap0) begin
          end else begin
            decode_index <= decode_index_advance;
            if (decode_end_o_equal[2]) begin
              decode_inner <= 0;
              decode_outer <= decode_outer + 1;
            end else decode_inner <= decode_inner_advance;
          end
        end
        state[$clog2(COORD)]: begin
          coordinate_product_q <= shared_coordinate_product;
        end
        state[$clog2(COORD_SUM)]: begin
          coordinate_sum_q <= coordinate_product_sum;
        end
        state[$clog2(COORD_BORROW)]: begin
          for (int axis = 0; axis < 2; axis++) begin
            coordinate_sum_q[axis][15:0] <= coordinate_low_difference[axis][15:0];
            coordinate_borrow_q[axis] <= coordinate_low_difference[axis][16];
          end
        end
        state[$clog2(COORD_PAD)]: ;
        state[$clog2(ADDRESS)]: begin
          if (!address_position_valid) begin
          end else if (!geometry_tile || col_idx != 0 || (!pred_busy && !cache_hint_pending)) begin
            pixel_product <= shared_coordinate_product[0];
          end
        end
        state[$clog2(ADDRESS_PIXEL)]: ;
        state[$clog2(ADDRESS_MERGE)]: channel_product <= shared_channel_product[0][31:0];
        state[$clog2(ADDRESS_BASE)]: group_base_addr <= group_address_sum;
        state[$clog2(ADDRESS_CHANNEL)]: ;
        state[$clog2(FETCH)]: ;
        default: ;
      endcase
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SIZE<2 || (SIZE & (SIZE-1))!=0) $fatal(1,"SIZE must be a power of two >=2");
    if (LANES<1 || LANES>16) $fatal(1,"LANES must be in [1,16]");
    if (NARROW_LANES<1) $fatal(1,"NARROW_LANES must be positive");
  end
`endif
`ifdef NPU_SIM_ASSERT
  initial forever @(posedge clk) if (rst_n) begin
    assert ($onehot(state));
    if (LANES <= 16 && LANES <= (1 << TILE_COUNT_W))
      assert ((chunk_lane_allowed & (chunk_lane_allowed + 1'b1)) == '0);
    if (wr_valid) begin
      assert (wr_mask!='0 && chunk_count!=0);
      assert (col_idx+TILE_COUNT_W'(chunk_count)<=cols_q && row_idx<rows_q);
    end
    if (cache_req_valid) begin
      assert (cache_req_addr>=c.input_base);
      assert ({1'b0,cache_req_addr} < {1'b0,c.input_base}+{1'b0,tensor_bytes});
    end
  end
`endif
  assign ox = 32'(ox_q);
  assign oy = 32'(oy_q);
  assign ky = 32'(ky_q);
  assign kx = 32'(kx_q);
  assign ch = 32'(ch_q);
  assign ky0 = 32'(ky0_q);
  assign kx0 = 32'(kx0_q);
  assign ch0 = 32'(ch0_q);

endmodule

// 描述符范围、填充和字命中各自完成后，独立选择下一运行状态。
module conv_im2col_descriptor_state #(
  parameter bit p_register_descriptor = 1'b0
) (
  input wire logic i_invalid,
  input wire logic i_fast,
  input wire logic i_padding,
  input wire logic i_word_hit,
  input wire logic i_cache_req_ready,
  output conv_im2col_frontend_pkg::st_t o_state
);
  import conv_im2col_frontend_pkg::*;

  always_comb begin
    o_state = IDLE;
    if (i_invalid) begin
      o_state = IDLE;
    end else if (i_fast) begin
      if (p_register_descriptor) o_state = DESCRIPTOR_CHECK;
      else if (i_padding) o_state = ZERO_STREAM;
      else if (i_word_hit) o_state = STREAM;
      else o_state = i_cache_req_ready ? WAIT_WORD : FETCH;
    end else if (p_register_descriptor) o_state = P_HISTORY;
    else o_state = P_DECODE;
  end
endmodule

// 地址资格独立译码，行位置不参与描述符候选数据的计算。
module conv_im2col_address_sources (
  input wire logic i_tap, i_incoming, i_row, i_stream, i_row_metadata,
  output logic [4:0] o_cache, o_saved
);
  assign o_cache[0] = !i_tap && i_incoming;
  assign o_cache[1] = i_tap;
  assign o_cache[2] = !i_tap && !i_incoming && i_row;
  assign o_cache[3] = !i_tap && !i_incoming && !i_row && i_stream;
  assign o_cache[4] = !i_tap && !i_incoming && !i_row && !i_stream;
  assign o_saved[0] = !i_row_metadata && !i_tap && i_incoming;
  assign o_saved[1] = !i_row_metadata && i_tap;
  assign o_saved[2] = i_row_metadata;
  assign o_saved[3] = !i_row_metadata && !i_tap && !i_incoming && i_stream;
  assign o_saved[4] = !i_row_metadata && !i_tap && !i_incoming && !i_stream;
endmodule

// 各字段的行推进及内核推进条件分别归并，避免与状态保存值串行计算。
module conv_im2col_stream_position (
  input wire logic i_chunk_end, i_row_last, i_row_base_valid, i_geometry_tile,
  input wire logic i_row_coordinate_valid, i_past_active, i_active_after,
  input wire logic i_group_end, i_coordinate_address_valid,
  output logic o_row_coordinate, o_row_data, o_tap_coordinate, o_tap_data
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

// 配置、描述符和运行分支只在末级选择完整的错误标志。
module conv_im2col_error_select (
  input wire logic i_configuration, i_commit,
  input wire logic [1:0] i_configuration_value, i_commit_value, i_operation_value,
  output logic [1:0] o_value
);
  assign o_value = i_configuration ? i_configuration_value :
      (i_commit ? i_commit_value : i_operation_value);
endmodule

// 传输接收选择两个已经完成的运行结果。
module conv_im2col_error_operation_select (
  input wire logic i_accept,
  input wire logic [1:0] i_waiting, i_accepted,
  output logic [1:0] o_value
);
  assign o_value = i_accept ? i_accepted : i_waiting;
endmodule

module conv_im2col_error_update (
  input wire logic [26:0] i_state,
  input wire logic i_error, i_configuration_complete, i_configuration_ok,
  input wire logic i_cfg_fire, i_basic_valid, i_tile_commit, i_tile_invalid,
  input wire logic i_stream_error, i_stream_accept,
  output logic o_error, o_tile_error
);
  import conv_im2col_frontend_pkg::*;
  logic saved_error, operation_failure, invalid_operation;
  logic [1:0][1:0] operation_value;
  logic [1:0] parallel_value;
  assign saved_error = i_configuration_complete ? !i_configuration_ok : i_error;
  assign operation_failure = !i_state[$clog2(DESCRIPTOR_CHECK)] && i_stream_error;
  assign invalid_operation = !(|i_state);
  // 两种传输结果分别完成配置和描述符选择，传输接收只进入最终一层。
  conv_im2col_error_select u_waiting (
    .i_configuration(i_cfg_fire), .i_commit(i_tile_commit),
    .i_configuration_value({1'b0, !i_basic_valid}),
    .i_commit_value({i_tile_invalid, saved_error || i_tile_invalid}),
    .i_operation_value({operation_failure,
        saved_error || operation_failure || invalid_operation}),
    .o_value(operation_value[0])
  );
  conv_im2col_error_select u_accepted (
    .i_configuration(i_cfg_fire), .i_commit(i_tile_commit),
    .i_configuration_value({1'b0, !i_basic_valid}),
    .i_commit_value({i_tile_invalid, saved_error || i_tile_invalid}),
    .i_operation_value({operation_failure, saved_error || operation_failure}),
    .o_value(operation_value[1])
  );
  conv_im2col_error_operation_select u_operation (
    .i_accept(i_stream_accept), .i_waiting(operation_value[0]),
    .i_accepted(operation_value[1]), .o_value(parallel_value)
  );
  always_comb begin
    o_error = i_error;
    o_tile_error = 1'b0;
    case (^{i_state, i_error, i_configuration_complete, i_configuration_ok,
             i_cfg_fire, i_basic_valid, i_tile_commit, i_tile_invalid,
             i_stream_error, i_stream_accept})
      1'b0, 1'b1: {o_tile_error, o_error} = parallel_value;
      default: begin
        // 未知控制值按各状态的过程式优先级选择。
        if (i_configuration_complete) o_error = !i_configuration_ok;
        case (1'b1)
          i_cfg_fire: begin o_error=!i_basic_valid; end
          i_tile_commit: if (i_tile_invalid) begin o_error=1'b1; o_tile_error=1'b1; end
          i_state[$clog2(DESCRIPTOR_CHECK)]: ;
          i_stream_error: begin o_error=1; o_tile_error=1; end
          i_stream_accept: ;
          (!i_tile_commit && i_stream_error !== 1'b1 && i_stream_accept !== 1'b1 &&
          (i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)])): ;
          i_state[$clog2(P_HISTORY)]: ;
          i_state[$clog2(P_DECODE)]: ;
          i_state[$clog2(P_START)]: ;
          i_state[$clog2(P_WAIT)]: ;
          i_state[$clog2(Q_DECODE)]: ;
          i_state[$clog2(Q_START)]: ;
          i_state[$clog2(Q_WAIT)]: ;
          i_state[$clog2(K_DECODE)]: ;
          i_state[$clog2(K_START)]: ;
          i_state[$clog2(K_WAIT)]: ;
          i_state[$clog2(COORD)]: ;
          i_state[$clog2(COORD_SUM)]: ;
          i_state[$clog2(COORD_BORROW)]: ;
          i_state[$clog2(COORD_PAD)]: ;
          i_state[$clog2(ADDRESS)]: ;
          i_state[$clog2(ADDRESS_PIXEL)]: ;
          i_state[$clog2(ADDRESS_PRODUCT)]: ;
          i_state[$clog2(ADDRESS_MERGE)]: ;
          i_state[$clog2(ADDRESS_BASE)]: ;
          i_state[$clog2(ADDRESS_CHANNEL)]: ;
          i_state[$clog2(ADDRESS_MATCH)]: ;
          i_state[$clog2(FETCH)]: ;
          (i_state[$clog2(IDLE)] && !i_cfg_fire && !i_tile_commit): ;
          default: begin o_error=1; end
        endcase
      end
    endcase
  end
endmodule

// 配置、描述符和流传输按既有优先级选择已准备的回绕字段。
(* keep_hierarchy = "yes" *)
module conv_im2col_wrap_update_select (
  input logic i_configuration, i_commit, i_descriptor_check,
  input logic i_stream_error, i_stream_accept, i_running,
  input logic [3:0][5:0] i_candidate,
  output logic [2:0] o_write, o_value
);
  always_comb begin
    {o_write, o_value} = '0;
    case (1'b1)
      i_configuration: {o_write, o_value} = i_candidate[0];
      i_commit: {o_write, o_value} = i_candidate[1];
      i_descriptor_check: {o_write, o_value} = '0;
      i_stream_error: {o_write, o_value} = '0;
      i_stream_accept: {o_write, o_value} = i_candidate[2];
      (!i_commit && i_stream_error !== 1'b1 && i_stream_accept !== 1'b1 && i_running): {o_write, o_value} = '0;
      default: {o_write, o_value} = i_candidate[3];
    endcase
  end
endmodule

// 空闲与输出完成分别准备接收资格，缓存返回在外层完成末级选择。
(* keep_hierarchy = "yes" *)
module conv_im2col_tile_context (
  input logic i_static_ready, i_idle, i_stream, i_zero_stream, i_wait_word,
  input logic i_write_ready, i_row_last, i_chunk_end,
  output logic [1:0] o_ready
);
  logic transfer_last;
  assign transfer_last = i_write_ready && i_row_last && i_chunk_end;
  assign o_ready[0] = i_static_ready && (i_idle || ((i_stream || i_zero_stream) && transfer_last));
  assign o_ready[1] = i_static_ready && i_wait_word && transfer_last;
endmodule

`default_nettype wire
