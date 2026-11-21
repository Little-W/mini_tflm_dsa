// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// Implicit im2col frontend. Does not change the PE array or allocate an expanded
// activation matrix in external memory. Feed tile descriptors from IA scheduling.
// Emits corrected signed-16 values to the existing IA tile RAM write interface.
module conv_im2col_frontend #(
  parameter int SIZE=16,
  parameter int SLOT_W=3,
  parameter int LANES=2,       // Corrected values written into independent IA banks
  parameter int CACHE_SETS=128,
  parameter int CACHE_WAYS=2,
  parameter int LINE_BYTES=16,
  parameter int BUS_WIDTH=32,
  parameter int NARROW_LANES=BUS_WIDTH/8,
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter bit REGISTER_CACHE_REQUEST=1'b0,
  // 描述符准备、请求保存和响应队列分别选择寄存边界。
  parameter bit REGISTER_DESCRIPTOR=1'b1,
  parameter bit REGISTER_ROW_ADDRESS=REGISTER_DESCRIPTOR,
  parameter int CACHE_RESPONSE_DEPTH=1,
  parameter int CW=$clog2(SIZE),
  parameter int RW=$clog2(SIZE+1)
) (
  input wire logic clk, rst_n,
  input wire logic cfg_valid,
  output logic cfg_ready,
  input conv_im2col_pkg::conv_cfg_t cfg,
  // Native IA scheduler context. Zero groups disables the geometry policy for
  // standalone clients that do not promise the native descriptor order.
  input wire logic [31:0] cfg_sched_r = 32'd0,
  input wire logic [31:0] cfg_sched_groups = 32'd0,
  input wire logic tile_valid,
  output logic tile_ready,
  input wire logic [31:0] tile_p0, tile_q0,
  input wire logic [RW-1:0] tile_rows,
  input wire logic [RW-1:0] tile_cols = '0, // Zero selects the full SIZE columns.
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
  // 缓存读取宽度随输出通道数扩展，最大读取范围限定在单个缓存行内。
  localparam int p_lane_bytes = LANES <= 4 ? 4 : (1 << $clog2(LANES));
  localparam int p_cache_read_bytes = p_lane_bytes < LINE_BYTES ? p_lane_bytes : LINE_BYTES;
  localparam int p_cache_read_width = 8 * p_cache_read_bytes;
  localparam int p_word_shift = $clog2(p_cache_read_bytes);
  // 每个状态保存独立的一位，数据选择直接读取对应状态位。
  typedef enum logic [21:0] {
    IDLE = 22'h000001,
    P_DECODE = 22'h000002,
    P_START = 22'h000004,
    P_WAIT = 22'h000008,
    Q_DECODE = 22'h000010,
    Q_START = 22'h000020,
    Q_WAIT = 22'h000040,
    K_DECODE = 22'h000080,
    K_START = 22'h000100,
    K_WAIT = 22'h000200,
    COORD = 22'h000400,
    COORD_SUM = 22'h000800,
    COORD_PAD = 22'h001000,
    ADDRESS = 22'h002000,
    ADDRESS_PIXEL = 22'h004000,
    ADDRESS_PRODUCT = 22'h008000,
    ADDRESS_BASE = 22'h010000,
    ADDRESS_CHANNEL = 22'h020000,
    FETCH = 22'h040000,
    WAIT_WORD = 22'h080000,
    STREAM = 22'h100000,
    ZERO_STREAM = 22'h200000
  } st_t;
  (* fsm_encoding = "none" *) st_t state;
  conv_cfg_t c;
  logic configured, cfg_ok, cfg_basic_valid, cfg_basic_saved;
  logic [1:0] cfg_prepare_phase;
  logic [31:0] cfg_input_hw, cfg_kernel_taps, cfg_position_product;
  logic [48:0] cfg_tensor_product;
  logic [47:0] cfg_reduction_product;
  logic cfg_address_overflow;
  logic [3:0] cfg_address_generate, cfg_address_propagate;
  logic [63:0] cfg_input_bytes, cfg_red;
  logic [31:0] cfg_positions;
  logic [31:0] reduction_len, position_count, tensor_bytes;
  localparam int p_row_low_w = RW < 32 ? RW : 31;
  localparam int p_row_high_w = 32 - p_row_low_w;
  logic [p_row_high_w-1:0] position_high_minus_one_q;
  logic tile_rows_in_range;
  logic tile_q_before_end;
  logic [3:0] tile_q_byte_before, tile_q_byte_equal;
  localparam int TILE_COUNT_W=$clog2(SIZE+1);
  localparam int CHUNK_COUNT_W=$clog2(LANES+1);
  localparam int p_group_low_w = LANES > 1 && LANES <= 32768 ? $clog2(LANES) : 1;
  localparam int p_group_high_w = 16 - p_group_low_w;
  logic [p_group_high_w-1:0] group_high_minus_one_q;
  logic [15:0] last_group_channel_q;
  logic [15:0] group_minus_two_q, group_minus_three_q, group_minus_four_q;
  localparam int p_saved_group_lanes = LANES > 4 && LANES <= 8 ? 8 : 4;
  logic [LANES-1:0] group_lane_allowed;
  logic [p_saved_group_lanes:0] group_range_q, group_range_cfg;
  logic [p_saved_group_lanes:1] group_at_least_q;
  logic [p_saved_group_lanes-1:0][15:0] group_last_channels_q;
  assign group_last_channels_q[0] = last_group_channel_q;
  assign group_last_channels_q[1] = group_minus_two_q;
  assign group_last_channels_q[2] = group_minus_three_q;
  assign group_last_channels_q[3] = group_minus_four_q;
  for (genvar boundary = 4; boundary < p_saved_group_lanes; boundary++) begin : g_saved_group_tail
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) group_last_channels_q[boundary] <= 16'(0-boundary-1);
      else if (cfg_valid && cfg_ready)
        group_last_channels_q[boundary] <= cfg.group_c - 16'(boundary+1);
    end
  end
  for (genvar boundary = 1; boundary <= p_saved_group_lanes; boundary++) begin : g_group_threshold
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) group_at_least_q[boundary] <= 1'b0;
      else if (cfg_valid && cfg_ready) group_at_least_q[boundary] <= cfg.group_c >= 16'(boundary);
    end
  end
  logic [5:0][15:0] group_range_channel;
  logic [5:0][p_saved_group_lanes:0] group_range_next;
  logic group_after_chunk;
  logic [31:0] p0, q0, tap0;
  logic [32:0] next_group_q;
  logic [TILE_COUNT_W-1:0] row_idx, col_idx, rows_q, cols_q, active_cols_q;
  logic [TILE_COUNT_W-1:0] next_row_idx;
  logic row_last_q, next_row_last;
  logic unused_row_index_carry;
  logic [TILE_COUNT_W-1:0] col_remaining, active_remaining;
  logic past_active_q;
  logic narrow_output;
  logic [16:0] group_remaining;
  logic [LANES-1:0] chunk_lane_allowed, word_lane_allowed, chunk_end_lane;
  (* keep = 1 *) logic [LANES-1:0] chunk_data_allowed;
  logic chunk_reaches_end;
  logic [15:0] ox_q, oy_q, ky_q, kx_q, ch_q, ky0_q, kx0_q, ch0_q;
  wire [31:0] ox=32'(ox_q), oy=32'(oy_q), ky=32'(ky_q), kx=32'(kx_q), ch=32'(ch_q);
  wire [31:0] ky0=32'(ky0_q), kx0=32'(kx0_q), ch0=32'(ch0_q);
  logic [32:0] q_current;
  localparam int COORD_W=35;
  localparam logic signed [COORD_W-1:0] p_coord_max = {1'b0,{(COORD_W-1){1'b1}}};
  logic signed [COORD_W-1:0] ix, iy;
  logic ix_step_below_limit;
  logic [COORD_W-1:0] ix_increment;
  logic unused_ix_increment_carry;
  logic [31:0] pixel_index;
  logic [31:0] coord_out_x,coord_out_y,coord_kernel_x,coord_kernel_y;
  logic [32:0] coord_sum_x,coord_sum_y;
  logic [31:0] pixel_product,channel_product,group_base_addr;
  logic [16:0] channel_byte_offset;
  logic [17:0] channel_addr_low;
  logic [14:0] channel_addr_high_next;
  logic [31:0] channel_addr;
  logic unused_channel_addr_carry;
  logic [31:0] tap_group_base,row_group_base,next_row_group_base,incoming_group_base;
  logic pad_q;
  logic [31:0] addr;
  logic [p_cache_read_width-1:0] word_buf;
  logic [31:0] word_addr;
  logic word_valid;
  logic addr_word_hit_q, current_word_hit;
  logic next_tap_saved_hit, next_byte_saved_hit, channel_saved_hit;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  logic [SLOT_W-1:0] slot_q;
  logic [31:0] decode_index, decode_outer, decode_inner;
  logic [2:0][31:0] decode_end_i_target;
  logic [2:0] decode_end_o_equal;
  logic cache_cfg_ready, cache_req_ready, cache_rsp_valid, cache_rsp_error;
  logic cache_req_valid, cache_rsp_ready, stream_next_request,stream_context;
  logic next_row_request, next_row_word_hit;
  logic [31:0] stream_request_addr;
  logic unused_stream_request_carry;
  logic column_after_chunk, active_after_chunk;
  logic [p_word_shift+1:0] byte_offset_sum;
  logic word_boundary;
  logic [LANES:0] chunk_selected;
  logic [LANES:0] step_word_boundary, step_saved_hit;
  assign chunk_selected[0] = !(|chunk_lane_allowed);
  for (genvar step = 1; step <= LANES; step++) begin : g_chunk_selected
    if (step == LANES) begin : g_last
      assign chunk_selected[step] = chunk_lane_allowed[step-1];
    end else begin : g_lower
      assign chunk_selected[step] = chunk_lane_allowed[step-1] && !(|chunk_lane_allowed[LANES-1:step]);
    end
  end
  logic incoming_request, incoming_context, incoming_word_hit, finishing_tile;
  logic incoming_same_position_fast, incoming_next_position_fast, incoming_next_tile_fast;
  logic incoming_position_same_tap, incoming_position_forward_tap, incoming_position_backward_tap;
  logic incoming_position_previous_row;
  logic incoming_skip_tap;
  logic window_next_valid, window_next_padding, window_next_last_col;
  logic window_forward_allowed_q, window_backward_allowed_q, window_previous_allowed_q;
  logic [31:0] window_next_p, window_next_q, window_next_pixel, window_next_addr, window_next_group_base;
  logic [31:0] window_next_tap;
  logic [15:0] window_next_x, window_next_y, window_next_ch, window_next_kx, window_next_ky;
  logic [p_saved_group_lanes:0] window_next_channel_range;
  logic [1:0] incoming_tile_group_fits;
  logic [31:0] next_position;
  logic [31:0] next_position_i_b;
  logic next_position_i_carry, next_position_o_equal, unused_next_position_carry;
  logic signed [COORD_W-1:0] window_next_ix, window_next_iy;
  logic cache_port_valid;
  logic [31:0] cache_req_addr;
  logic request_pending, cache_port_ready, request_bypass;
  logic [31:0] current_req_index, current_req_epoch;
  logic [31:0] request_addr_q, request_index_q, request_epoch_q;
  logic [15:0] request_y_q;
  logic [31:0] request_progress_q;
  logic retire_enabled_q, short_pixel_q;
  logic [3:0] retire_shift_q;
  logic [15:0] retire_last_row_q, second_last_row_q, last_output_col_q, second_last_col_q;
  logic [15:0] last_kernel_col_q;
  logic [15:0] last_input_col_q;
  logic kernel_width_valid_q;
  logic request_geometry_q, request_event_first_q, request_index_valid_q;
  logic [p_cache_read_width-1:0] cache_rsp_data;
  logic [p_cache_read_width-1:0] selected_word;
  logic [p_cache_read_width-1:0] stream_word;
  logic [7:0] offset_high_plus_one, offset_high_minus_one;
  logic unused_offset_high_add_carry, unused_offset_high_sub_carry;
  logic [LANES-1:0][7:0] selected_s8_byte, corrected_s8_high;
  logic [LANES-1:0][8:0] corrected_s8_low;
  logic [LANES-1:0][15:0] corrected_s8_value;
  logic pred_cfg_eligible, pred_enabled, pred_busy, pred_done, pred_start;
  logic pred_cfg_busy, cache_cfg_pending, cache_config_valid;
  logic pred_cfg_pending;
  logic [31:0] predictor_cfg_r;
  logic [31:0] pred_rank, group_q, groups_q;
  logic [31:0] predictor_position;
  logic unused_predictor_position_carry;
  logic geometry_tile, line_hint_valid, cache_hint_pending;
  logic [31:0] line_hint_rank;

  logic [3:0] p_cache_valid;
  logic [31:0] p_cache_key[4];
  logic [15:0] p_cache_y[4],p_cache_x[4];
  logic last_p_valid;
  logic [31:0] last_p,last_p_limit;
  logic [15:0] last_y,last_x;
  logic p_fast_valid;
  logic p_fast_wrap;
  logic [31:0] p_fast_y,p_fast_x,p_decode;
  logic [15:0] p_delta, p_history_delta_q, p_wrap_target_q;
  logic [16:0] p_sum_reduced;
  logic unused_p_sum_carry, unused_p_sum_reduced_carry;
  logic [16:0] p_sum;
  logic [15:0] p_sum_wrap_i_a, p_sum_wrap_i_b, p_sum_wrap_i_target;
  logic p_sum_wrap_i_carry_in, p_sum_wrap_o_equal;
  logic [15:0] p_sum_wrap_carry;
  logic unused_p_sum_wrap_carry;
  logic [15:0] p_sum_last_i_a, p_sum_last_i_b, p_sum_last_i_target;
  logic p_sum_last_i_carry_in, p_sum_last_o_equal;
  logic incoming_fast, incoming_q_fast, incoming_padding;
  logic incoming_group_fits;
  logic incoming_tap_wrap;
  logic [31:0] incoming_tap,incoming_ch,incoming_ky,incoming_kx,incoming_addr;
  logic signed [COORD_W-1:0] incoming_ix,incoming_iy;
  logic signed [COORD_W-1:0] incoming_step_ix, incoming_wrap_ix, incoming_wrap_iy;
  logic incoming_base_padding, incoming_step_padding, incoming_wrap_padding;
  logic [31:0] incoming_pixel;
  logic [1:0] p_cache_select;
  logic [31:0] req_index, req_epoch, request_retire;
  logic [1:0][15:0] retirement_input;
  logic [1:0][31:0] retirement_result;
  logic req_index_valid,window_index_valid_q;
  logic [4:0] window_index_shift_q;
  logic pf_valid, pf_ready;
  logic [31:0] pf_addr, pf_index, pf_epoch;
  logic pf_index_valid;
  logic [3:0] prefetch_phase;
  logic [31:0] pf_distance_q, pf_step_q, pf_address_calc, pf_channel_product;
  logic pf_offer_valid;
  wire prefetch_active = prefetch_phase!=0;
  logic signed [COORD_W-1:0] pfa_x, pfa_y;
  logic [31:0] pfa_channel, pfa_origin_channel, pfa_output_x, pfa_output_y;
  logic [31:0] pfa_kernel_x, pfa_rows, pfa_cols;
  logic [15:0] pfa_kernel_y;
  logic pf_stream_lookahead;
  logic [31:0] pfa_ref_addr, pfa_ref_index, pfa_ref_epoch;
  logic pfa_ref_index_valid;
  logic [31:0] pf0_x, pf0_y, pf0_channel, pf0_epoch;
  logic [31:0] pf0_ref_addr, pf0_ref_index, pf0_ref_epoch, pf0_ref_retire;
  logic pf0_ref_index_valid, pf0_fragment, pf0_coordinate_valid;
  logic [31:0] pf1_pixel, pf1_channel, pf1_epoch, pf1_retire;
  logic [31:0] pf1_ref_addr, pf1_ref_index, pf1_ref_epoch, pf1_ref_retire;
  logic pf1_ref_index_valid, pf1_fragment, pf1_coordinate_valid;
  logic [31:0] pf_x, pf_y, pf_step, pf_channel, pf_distance;
  logic signed [16:0] pf_y_delta_q;
  logic signed [17:0] pf_y_wrap_delta_q;
  logic [31:0] pf_y_base_q, pf_y_wrapped_q, pf_kernel_advance_q;
  logic [2:0][31:0] pf_prepare_i_a, pf_prepare_i_b, pf_prepare_o_sum;
  logic pf_prepare_i_carry;
  logic [2:0] unused_pf_prepare_carry;
  logic signed [16:0] pf_y_delta;
  logic signed [17:0] pf_y_wrap_delta;
  logic [15:0] pf_y_step;
  logic [31:0] pixel_bytes;
  logic [31:0] cfg_pixel_bytes, cfg_line_pixels, cfg_pf_step, pf_step_base;
  logic pf_coordinate_valid;
  logic fragment_image_fits, pf_next_fragment;
  logic [4:0] current_q_div3;
  logic [15:0] current_q_remainder;
  logic signed [COORD_W-1:0] request_y;
  logic [31:0] incoming_req_index;
  logic [31:0] request_output_y, incoming_epoch_channel, incoming_req_epoch;
  logic unused_incoming_epoch_carry;
  logic [4:0][31:0] epoch_i_a, epoch_i_b, epoch_o_sum;
  logic epoch_i_carry;
  logic [4:0] unused_epoch_carry;
  logic [31:0] stream_epoch_xor, stream_epoch_carry;
  logic [31:0] stream_channel_full;
  logic [31:0] stream_channel_i_a, stream_channel_i_b;
  logic unused_stream_channel_carry;
  logic signed [COORD_W-1:0] pf_wrap_x;
  logic pf_window_ahead, pf_window_row_valid_q;
  logic pf_ahead_two, pf_wrap_once, pf_wrap_twice;
  logic signed [32:0] pf_window_dx_q, pf_fragment_dx_q, row_pair_dx;
  logic [16:0] pf_window_dy_q;
  logic signed [COORD_W-1:0] pf_window_x,pf_window_y;
  logic [31:0] next_byte_addr;
  logic [COORD_W-1:0] bound_a [7], bound_b [7];
  logic [COORD_W-1:0] bound_sum [7];
  logic [15:0] bound_limit [7];
  logic [6:0] bound_valid;
  logic [31:0] next_tap_delta, incoming_delta;
  logic [p_word_shift:0] next_word_low_sum;
  logic [p_word_shift:0] incoming_step_low_sum, incoming_wrap_low_sum;
  logic [31-p_word_shift:0] next_word_i_a, next_word_i_b, next_word_i_target;
  logic next_word_i_carry_in, next_word_o_equal;
  logic [31-p_word_shift:0] incoming_word_i_a, incoming_word_i_b, incoming_word_i_target;
  logic incoming_word_i_carry_in, incoming_word_o_equal;
  logic [31-p_word_shift:0] incoming_live_word_i_target;
  logic incoming_live_word_o_equal;
  logic [1:0] address_step_phase;
  logic signed [32:0] row_wrap_dx, tap_wrap_dx;
  logic signed [32:0] row_y_pixels, tap_y_pixels, row_wrap_pixels, tap_wrap_pixels;
  logic [31:0] row_step_bytes, tap_step_bytes, row_wrap_bytes, tap_wrap_bytes, group_bytes;
  logic signed [COORD_W-1:0] tap_pair_dx;
  logic [31:0] tap_pair_pixels, tap_pair_bytes;
  logic [2:0][COORD_W-1:0] tap_pair_i_a, tap_pair_i_b, tap_pair_o_sum;
  logic tap_pair_i_carry;
  logic [2:0] unused_tap_pair_carry;
  logic row_base_valid, coordinate_address_valid;
  logic row_coordinate_valid,current_coordinate_valid;
  logic signed [COORD_W-1:0] row_base_ix, row_base_iy;
  logic [31:0] row_base_pixel;
  logic [31:0] row_base_addr;
  logic row_wrap, tap_wrap, next_row_padding, next_tap_padding;
  logic row_wrap_q, tap_wrap_q, incoming_tap_wrap_q;
  logic [15:0] cfg_last_output_col, cfg_last_kernel_col;
  logic unused_cfg_output_col_carry, unused_cfg_kernel_col_carry;
  logic [15:0] tap_next_i_a, tap_next_i_b, tap_next_i_target;
  logic tap_next_i_carry_in, tap_next_o_equal;
  logic [15:0] row_next_i_a, row_next_i_b, row_next_i_target;
  logic row_next_i_carry_in, row_next_o_equal;
  logic signed [COORD_W-1:0] next_row_ix, next_row_iy, next_tap_ix, next_tap_iy;
  logic [31:0] next_row_pixel, next_tap_pixel;
  logic [31:0] next_row_addr, next_tap_addr;
  logic [32:0] next_q_current;
  logic [15:0] next_channel;
  logic [31:0] incoming_pixel_delta, incoming_pixel_next;
  logic [16:0] incoming_pixel_low;
  logic [15:0] incoming_pixel_high_zero, incoming_pixel_high_one;
  logic unused_incoming_pixel_high_zero_carry, unused_incoming_pixel_high_one_carry;
  logic [5:0] incoming_fast_i_flags;
  logic [1:0] incoming_position_equal;
  logic incoming_q_equal;
  logic [3:0][32:0] incoming_tap_match_i_a, incoming_tap_match_i_b;
  logic [3:0][32:0] incoming_tap_match_i_target;
  logic [3:0] incoming_tap_match_i_carry_in, incoming_tap_match_o_equal;
  logic [31:0] incoming_tile_match_i_a, incoming_tile_match_i_b, incoming_tile_match_i_target;
  logic incoming_tile_match_i_carry_in, incoming_tile_match_o_equal;
  logic signed [COORD_W-1:0] window_forward_ix, window_backward_ix, window_previous_iy;
  logic signed [COORD_W-1:0] incoming_skip_ix, incoming_skip_iy;
  logic window_forward_padding, window_backward_padding, window_previous_padding;
  logic incoming_skip_padding, window_shift_padding;
  logic channel_descriptor_valid, channel_accept_fire, tile_ready_context;
  logic [15:0] channel_update, channel_value;
  logic [5:0] channel_accept_i_flags;
  typedef struct packed {
    logic invalid, fast, padding, word_hit, output_position_update, output_wrap, kernel_last;
    logic geometry, narrow_output;
    logic [31:0] position, reduction, group_index;
    logic [TILE_COUNT_W-1:0] rows, columns, active_columns;
    logic [SLOT_W-1:0] slot;
    logic [32:0] next_group;
    logic [31:0] tap, channel, kernel_x, kernel_y;
    logic signed [COORD_W-1:0] input_x, input_y;
    logic [31:0] pixel, address, group_address;
    logic [15:0] output_x, output_y;
    logic [p_saved_group_lanes:0] channel_range;
    logic signed [COORD_W-1:0] coordinate_dx, coordinate_dy;
    logic coordinate_x_carry, coordinate_y_carry;
    logic [8:0] padding_select, padding_value;
    logic [9:0] word_select, word_value;
  } prepared_tile_t;
  prepared_tile_t preparing_tile, prepared_tile_q, committing_tile;
  logic tile_prepared_valid, tile_capture, tile_commit;
  logic [p_cache_read_width-1:0] prepared_word_data;
  logic committing_saved_word_hit, committing_live_word_hit;
  (* keep = 1 *) logic prepared_live_word_match;
  logic [8:0] prepared_padding_select, prepared_padding_value;
  (* keep = 1 *) logic [9:0] prepared_word_select;
  logic [9:0] prepared_word_value;
  logic [9:0][1:0][31:0] prepared_address_candidate;
  logic [1:0][31:0] prepared_address;
  logic [9:0][1:0] prepared_word_match;
  logic signed [COORD_W-1:0] prepared_coordinate_x, prepared_coordinate_y;
  logic signed [COORD_W-1:0] prepared_coordinate_dx, prepared_coordinate_dy;
  logic [1:0] prepared_coordinate_carry;
  logic [1:0][COORD_W-1:0] committing_coordinate;
  logic [1:0] unused_committing_coordinate_carry;
  logic [TILE_COUNT_W-1:0] prepared_columns, prepared_active_columns;
  logic [32:0] prepared_next_group;
  logic [32:0] prepared_group_i_a, prepared_group_i_b;
  logic prepared_group_i_carry, unused_prepared_group_carry;


  // 描述符的四段范围比较并行进行，最高不同字节决定整体大小关系。
  for (genvar byte_index = 0; byte_index < 4; byte_index++) begin : g_tile_q_range
    assign tile_q_byte_before[byte_index] =
      tile_q0[byte_index*8 +: 8] < reduction_len[byte_index*8 +: 8];
    assign tile_q_byte_equal[byte_index] =
      tile_q0[byte_index*8 +: 8] == reduction_len[byte_index*8 +: 8];
  end
  assign tile_q_before_end = tile_q_byte_before[3] ||
    (tile_q_byte_equal[3] && tile_q_byte_before[2]) ||
    ((&tile_q_byte_equal[3:2]) && tile_q_byte_before[1]) ||
    ((&tile_q_byte_equal[3:1]) && tile_q_byte_before[0]);

  if (RW < 32) begin : g_tile_row_range
    logic [p_row_low_w:0] row_end_low;
    logic high_before_end, high_at_end, high_before_end_by_one, low_within_end;

    // 描述符低位相加与高位比较并行，末端只合并低位进位和边界关系。
    assign row_end_low = {1'b0, tile_p0[p_row_low_w-1:0]} + {1'b0, tile_rows};
    if (p_row_high_w <= 27) begin : g_high_range_tree
      logic [26:0] row_high_a, row_high_b, row_high_last;
      logic [8:0] leaf_before, leaf_equal, leaf_last_equal;
      logic [2:0] group_before, group_equal;

      // 每三位并行比较，再按高位优先合并各组结果。
      assign row_high_a = 27'(tile_p0[31:p_row_low_w]);
      assign row_high_b = 27'(position_count[31:p_row_low_w]);
      assign row_high_last = 27'(position_high_minus_one_q);
      assign high_before_end_by_one = &leaf_last_equal;
      for (genvar part = 0; part < 9; part++) begin : g_leaf
        assign leaf_before[part] = row_high_a[3*part +: 3] < row_high_b[3*part +: 3];
        assign leaf_equal[part] = row_high_a[3*part +: 3] == row_high_b[3*part +: 3];
        assign leaf_last_equal[part] = row_high_a[3*part +: 3] == row_high_last[3*part +: 3];
      end
      for (genvar part = 0; part < 3; part++) begin : g_group
        assign group_equal[part] = &leaf_equal[3*part +: 3];
        assign group_before[part] = leaf_before[3*part+2] ||
          (leaf_equal[3*part+2] && leaf_before[3*part+1]) ||
          (leaf_equal[3*part+2] && leaf_equal[3*part+1] && leaf_before[3*part]);
      end
      assign high_at_end = &group_equal;
      assign high_before_end = group_before[2] ||
        (group_equal[2] && group_before[1]) ||
        (group_equal[2] && group_equal[1] && group_before[0]);
    end else begin : g_high_range_wide
      assign high_before_end = tile_p0[31:p_row_low_w] < position_count[31:p_row_low_w];
      assign high_at_end = tile_p0[31:p_row_low_w] == position_count[31:p_row_low_w];
      assign high_before_end_by_one = tile_p0[31:p_row_low_w] == position_high_minus_one_q;
    end
    assign low_within_end = row_end_low[p_row_low_w-1:0] <= position_count[p_row_low_w-1:0];
    assign tile_rows_in_range =
      (high_before_end && (!row_end_low[p_row_low_w] || !high_before_end_by_one || low_within_end)) ||
      (high_at_end && !row_end_low[p_row_low_w] && low_within_end);
  end else begin : g_tile_row_range_wide
    assign tile_rows_in_range = {1'b0, tile_p0} + 33'(tile_rows) <= {1'b0, position_count};
  end

  // 通道偏移最多十七位，低位求和与高位加一并行，末端按低位进位选择。
  assign channel_byte_offset = c.input_s16 ? {ch_q, 1'b0} : {1'b0, ch_q};
  assign channel_addr_low = {1'b0, group_base_addr[16:0]} + {1'b0, channel_byte_offset};
  assign {unused_channel_addr_carry, channel_addr_high_next} =
    {1'b0, group_base_addr[31:17]} + 16'd1;
  assign channel_addr = {
    channel_addr_low[17] ? channel_addr_high_next : group_base_addr[31:17], channel_addr_low[16:0]};

  // 末列判断随坐标寄存，连续输出周期直接使用已保存的比较结果。
  assign {unused_cfg_output_col_carry, cfg_last_output_col} = {1'b0, cfg.output_w} - 17'd1;
  assign {unused_cfg_kernel_col_carry, cfg_last_kernel_col} = {1'b0, cfg.kernel_w} - 17'd1;

  // 列号加一后的末列关系直接检查进位一致性，与列号结果并行。
  assign tap_next_i_a = kx_q;
  assign tap_next_i_b = 16'd0;
  assign tap_next_i_target = last_kernel_col_q;
  assign tap_next_i_carry_in = 1'b1;
  add_equal #(.p_width(16)) u_tap_next (
    .i_a(tap_next_i_a), .i_b(tap_next_i_b), .i_target(tap_next_i_target),
    .i_carry_in(tap_next_i_carry_in), .o_equal(tap_next_o_equal)
  );
  assign row_next_i_a = ox_q;
  assign row_next_i_b = 16'd0;
  assign row_next_i_target = last_output_col_q;
  assign row_next_i_carry_in = 1'b1;
  add_equal #(.p_width(16)) u_row_next (
    .i_a(row_next_i_a), .i_b(row_next_i_b), .i_target(row_next_i_target),
    .i_carry_in(row_next_i_carry_in), .o_equal(row_next_o_equal)
  );

  // 高位是否为零直接检查逐位进位，低十六位独立完成图像范围比较。
  assign bound_a[0] = row_base_ix;
  assign bound_a[1] = row_base_iy;
  assign bound_a[2] = ix;
  assign bound_a[3] = iy;
  assign bound_b[0] = row_wrap ? COORD_W'(row_wrap_dx) : COORD_W'(c.stride_w);
  assign bound_b[1] = row_wrap ? COORD_W'(c.stride_h) : '0;
  assign bound_b[2] = tap_wrap ? COORD_W'(tap_wrap_dx) : COORD_W'(c.dilation_w);
  assign bound_b[3] = tap_wrap ? COORD_W'(c.dilation_h) : '0;
  assign bound_limit[0] = c.input_w;
  assign bound_limit[1] = c.input_h;
  assign bound_limit[2] = c.input_w;
  assign bound_limit[3] = c.input_h;
  assign bound_a[4] = row_base_ix;
  assign bound_a[5] = row_base_ix;
  assign bound_a[6] = row_base_iy;
  assign bound_b[4] = COORD_W'(c.dilation_w);
  assign bound_b[5] = COORD_W'(tap_wrap_dx);
  assign bound_b[6] = COORD_W'(c.dilation_h);
  assign bound_limit[4] = c.input_w;
  assign bound_limit[5] = c.input_w;
  assign bound_limit[6] = c.input_h;
  for (genvar axis = 0; axis < 7; axis++) begin : g_coordinate_bound
    logic [8:0] byte_low_sum, byte_high_zero, byte_high_one;
    logic unused_coordinate_carry;
    logic byte_low_before, byte_high_zero_before, byte_high_one_before;
    logic low_carry, low_before, high_o_equal;

    // 高字节分别计算两种进位及边界关系，低字节只选择最终结果。
    logic byte_low_i_carry;
    assign byte_low_i_carry = 1'b0;
    parallel_prefix_add #(.p_width(8), .p_group_width(4), .p_preserve_groups(1'b1)) u_byte_low_sum (
      .i_a(bound_a[axis][7:0]), .i_b(bound_b[axis][7:0]), .i_carry(byte_low_i_carry),
      .o_sum(byte_low_sum[7:0]), .o_carry(byte_low_sum[8])
    );
    assign byte_high_zero = {1'b0, bound_a[axis][15:8]} + {1'b0, bound_b[axis][15:8]};
    // 两个九位补数之和取反，得到含固定进位的完整高字节和。
    assign byte_high_one = ~(~{1'b0, bound_a[axis][15:8]} + ~{1'b0, bound_b[axis][15:8]});
    logic coordinate_i_carry;
    assign coordinate_i_carry = 1'b0;
    // 完整坐标使用四位分组进位，范围判断保持独立的字节比较。
    parallel_prefix_add #(.p_width(COORD_W), .p_group_width(4), .p_preserve_groups(1'b1)) u_coordinate_sum (
      .i_a(bound_a[axis]), .i_b(bound_b[axis]), .i_carry(coordinate_i_carry),
      .o_sum(bound_sum[axis]), .o_carry(unused_coordinate_carry)
    );
    assign byte_low_before = byte_low_sum[7:0] < bound_limit[axis][7:0];
    assign byte_high_zero_before = byte_high_zero[7:0] < bound_limit[axis][15:8] ||
      (byte_high_zero[7:0] == bound_limit[axis][15:8] && byte_low_before);
    assign byte_high_one_before = byte_high_one[7:0] < bound_limit[axis][15:8] ||
      (byte_high_one[7:0] == bound_limit[axis][15:8] && byte_low_before);
    assign low_carry = byte_low_sum[8] ? byte_high_one[8] : byte_high_zero[8];
    assign low_before = byte_low_sum[8] ? byte_high_one_before : byte_high_zero_before;
    if (axis == 1 || axis == 3 || axis == 4 || axis == 6) begin : g_positive_step
      // 正步长的高位全零，进位分别对应全零或全一的原坐标高位。
      assign high_o_equal = low_carry ? (&bound_a[axis][COORD_W-1:16]) :
        !(|bound_a[axis][COORD_W-1:16]);
    end else begin : g_signed_step
      logic [COORD_W-17:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry_in;
      assign high_i_a = bound_a[axis][COORD_W-1:16];
      assign high_i_b = bound_b[axis][COORD_W-1:16];
      assign high_i_target = '0;
      assign high_i_carry_in = low_carry;
      add_equal #(.p_width(COORD_W-16)) u_high_zero (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry_in), .o_equal(high_o_equal)
      );
    end
    assign bound_valid[axis] = high_o_equal && low_before;
  end

  // 数据字匹配比较读取范围以外的高位，字内偏移单独提供进位。
  assign next_tap_delta = tap_wrap ? tap_wrap_bytes : tap_step_bytes;
  assign next_word_low_sum = {1'b0, tap_group_base[p_word_shift-1:0]} + {1'b0, next_tap_delta[p_word_shift-1:0]};
  assign next_word_i_a = tap_group_base[31:p_word_shift];
  assign next_word_i_b = next_tap_delta[31:p_word_shift];
  assign next_word_i_target = addr[31:p_word_shift];
  assign next_word_i_carry_in = next_word_low_sum[p_word_shift];
  add_equal #(.p_width(32-p_word_shift)) u_next_word (
    .i_a(next_word_i_a), .i_b(next_word_i_b), .i_target(next_word_i_target),
    .i_carry_in(next_word_i_carry_in), .o_equal(next_word_o_equal)
  );
  // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。
  assign incoming_step_low_sum = {1'b0, row_base_addr[p_word_shift-1:0]} + {1'b0, tap_step_bytes[p_word_shift-1:0]};
  assign incoming_wrap_low_sum = {1'b0, row_base_addr[p_word_shift-1:0]} + {1'b0, tap_wrap_bytes[p_word_shift-1:0]};
  assign incoming_word_i_a = row_base_addr[31:p_word_shift];
  assign incoming_word_i_b = incoming_delta[31:p_word_shift];
  assign incoming_word_i_target = word_addr[31:p_word_shift];
  add_equal #(.p_width(32-p_word_shift), .p_use_lut(1'b0)) u_incoming_word (
    .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_word_i_target),
    .i_carry_in(incoming_word_i_carry_in), .o_equal(incoming_word_o_equal)
  );
  // 两个来源的数据字提前完成比较，当前传输的完成条件只选择一位命中结果。
  assign incoming_live_word_i_target = addr[31:p_word_shift];
  add_equal #(.p_width(32-p_word_shift), .p_use_lut(1'b0)) u_incoming_live_word (
    .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_live_word_i_target),
    .i_carry_in(incoming_word_i_carry_in), .o_equal(incoming_live_word_o_equal)
  );


  if (CHUNK_COUNT_W + 1 < 32) begin : g_byte_address
    localparam int p_step_width = CHUNK_COUNT_W + 1;
    logic [p_step_width-1:0] byte_step;
    logic [p_step_width:0] address_low;
    logic [31-p_step_width:0] address_high_next;
    logic unused_address_carry;

    // 块内字节步长仅影响低位，高位加一提前完成。
    assign byte_step = c.input_s16 ? {chunk_count, 1'b0} : {1'b0, chunk_count};
    if (LANES <= 8) begin : g_parallel_byte_step
      (* keep = 1 *) logic [LANES:0][p_step_width:0] low_for_step;
      // 固定小步长按位生成进位，常量传播后每位只依赖少量地址位。
      function automatic logic [p_step_width:0] add_byte_step(
        input logic [p_step_width-1:0] value,
        input logic [p_step_width:0] amount
      );
        logic [p_step_width:0] extended_value, sum;
        logic [p_step_width+1:0] carry;
        extended_value = {1'b0, value};
        carry = '0;
        for (int bit_index = 0; bit_index <= p_step_width; bit_index++) begin
          sum[bit_index] = extended_value[bit_index] ^ amount[bit_index] ^ carry[bit_index];
          carry[bit_index+1] = (extended_value[bit_index] && amount[bit_index]) ||
            ((extended_value[bit_index] ^ amount[bit_index]) && carry[bit_index]);
        end
        case (^{value, amount})
          1'b0, 1'b1: add_byte_step = sum;
          default: add_byte_step = 'x;
        endcase
      endfunction
      // 每种传输数量先计算低位地址，通道资格只选择完整候选。
      for (genvar step = 0; step <= LANES; step++) begin : g_step
        logic [p_step_width:0] low_s8, low_s16;
        assign low_s8 = add_byte_step(addr[p_step_width-1:0], (p_step_width+1)'(step));
        assign low_s16 = add_byte_step(addr[p_step_width-1:0], (p_step_width+1)'(2*step));
        assign low_for_step[step] = c.input_s16 ? low_s16 : low_s8;
      end
      always_comb begin
        address_low = '0;
        for (int step = 0; step <= LANES; step++)
          address_low |= {(p_step_width+1){chunk_selected[step]}} & low_for_step[step];
      end
    end else begin : g_encoded_byte_step
      assign address_low = {1'b0, addr[p_step_width-1:0]} + {1'b0, byte_step};
    end
    assign {unused_address_carry, address_high_next} =
      {1'b0, addr[31:p_step_width]} + (33-p_step_width)'(1);
    assign next_byte_addr = {
      address_low[p_step_width] ? address_high_next : addr[31:p_step_width],
      address_low[p_step_width-1:0]};
  end else begin : g_byte_address_wide
    logic unused_address_carry;
    assign {unused_address_carry, next_byte_addr} =
      {1'b0, addr} + {1'b0, (32'(chunk_count) << c.input_s16)};
  end

  if (CHUNK_COUNT_W < 33) begin : g_reduction_position
    logic [CHUNK_COUNT_W:0] position_low;
    logic [32-CHUNK_COUNT_W:0] position_high_next;
    logic unused_position_carry;

    // 当前归约位置使用同一短步长，高位加一与低位求和并行。
    assign position_low = {1'b0, q_current[CHUNK_COUNT_W-1:0]} + {1'b0, chunk_count};
    assign {unused_position_carry, position_high_next} =
      {1'b0, q_current[32:CHUNK_COUNT_W]} + (34-CHUNK_COUNT_W)'(1);
    assign next_q_current = {
      position_low[CHUNK_COUNT_W] ? position_high_next : q_current[32:CHUNK_COUNT_W],
      position_low[CHUNK_COUNT_W-1:0]};
  end else begin : g_reduction_position_wide
    logic unused_position_carry;
    assign {unused_position_carry, next_q_current} = {1'b0, q_current} + 34'(chunk_count);
  end

  if (CHUNK_COUNT_W < 16) begin : g_channel_position
    logic [CHUNK_COUNT_W:0] channel_low;
    logic [15-CHUNK_COUNT_W:0] channel_high_next;
    logic unused_channel_carry;

    // 通道索引与短步长相加，高位候选不等待传输通道数。
    assign channel_low = {1'b0, ch_q[CHUNK_COUNT_W-1:0]} + {1'b0, chunk_count};
    assign {unused_channel_carry, channel_high_next} =
      {1'b0, ch_q[15:CHUNK_COUNT_W]} + (17-CHUNK_COUNT_W)'(1);
    assign next_channel = {
      channel_low[CHUNK_COUNT_W] ? channel_high_next : ch_q[15:CHUNK_COUNT_W],
      channel_low[CHUNK_COUNT_W-1:0]};
  end else begin : g_channel_position_wide
    logic unused_channel_carry;
    assign {unused_channel_carry, next_channel} = {1'b0, ch_q} + 17'(chunk_count);
  end

  logic [4:0][31:0] movement_i_a, movement_i_b, movement_o_sum;
  logic movement_i_carry;
  logic [4:0] unused_movement_carry;
  logic [6:0][1:0][31:0] incoming_address_i_a, incoming_address_i_b;
  logic [6:0][1:0][31:0] incoming_address_left, incoming_address_right, incoming_address_sum;
  logic [6:0] incoming_address_carry;
  logic [6:0][1:0] unused_incoming_address_carry;
  logic [6:0][1:0] incoming_candidate_word_match;
  logic [1:0] incoming_window_word_match, incoming_skip_word_match;
  logic [1:0] next_row_word_match, incoming_advanced_word_match;

  // 双核位置步长在配置准备期间保存，运行时只执行一次地址或坐标加法。
  assign tap_pair_i_a = {COORD_W'(tap_wrap_bytes), COORD_W'(32'(tap_wrap_pixels)), COORD_W'(tap_wrap_dx)};
  assign tap_pair_i_b = {COORD_W'(tap_step_bytes), COORD_W'(c.dilation_w), COORD_W'(c.dilation_w)};
  assign tap_pair_i_carry = 1'b0;
  for (genvar source = 0; source < 3; source++) begin : g_tap_pair
    parallel_prefix_add #(.p_width(COORD_W), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(tap_pair_i_a[source]), .i_b(tap_pair_i_b[source]), .i_carry(tap_pair_i_carry),
      .o_sum(tap_pair_o_sum[source]), .o_carry(unused_tap_pair_carry[source])
    );
  end
  always_ff @(posedge clk) begin
    if (address_step_phase == 2'd2) tap_pair_dx <= $signed(tap_pair_o_sum[0]);
    if (address_step_phase == 2'd1) tap_pair_pixels <= tap_pair_o_sum[1][31:0];
    if (address_step_phase == 2'd0) tap_pair_bytes <= tap_pair_o_sum[2][31:0];
  end

  // 行、核位置和像素地址各自保留完整三十二位，分组进位限制串行算术长度。
  assign movement_i_a = {pixel_index, tap_group_base, row_base_pixel, row_group_base, row_base_addr};
  assign movement_i_b[0] = row_wrap ? row_wrap_bytes : row_step_bytes;
  assign movement_i_b[1] = movement_i_b[0];
  assign movement_i_b[2] = row_wrap ? 32'(row_wrap_pixels) : {16'd0, c.stride_w};
  assign movement_i_b[3] = tap_wrap ? tap_wrap_bytes : tap_step_bytes;
  assign movement_i_b[4] = tap_wrap ? 32'(tap_wrap_pixels) : {16'd0, c.dilation_w};
  assign movement_i_carry = 1'b0;
  for (genvar source = 0; source < 5; source++) begin : g_movement_sum
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(movement_i_a[source]), .i_b(movement_i_b[source]), .i_carry(movement_i_carry),
      .o_sum(movement_o_sum[source]), .o_carry(unused_movement_carry[source])
    );
  end

  // 七种地址候选依次为核步进、核换行、跨两个核列、跨核行及列、
  // 已保存窗口的前向、后向、上一核行；两个端口分别计算数据和通道组地址。
  for (genvar candidate = 0; candidate < 7; candidate++) begin : g_incoming_address
    assign incoming_address_carry[candidate] = candidate == 5 || candidate == 6;
    for (genvar base = 0; base < 2; base++) begin : g_base
      assign incoming_address_i_a[candidate][base] = candidate < 4 ?
        (base == 0 ? row_base_addr : row_group_base) :
        (base == 0 ? window_next_addr : window_next_group_base);
      assign incoming_address_i_b[candidate][base] =
        candidate == 1 ? tap_wrap_bytes : candidate == 3 ? tap_pair_bytes :
        candidate == 2 ? tap_step_bytes << 1 :
        candidate == 5 ? ~tap_step_bytes : candidate == 6 ? ~tap_pair_bytes : tap_step_bytes;
      assign incoming_address_left[candidate][base] = incoming_address_i_a[candidate][base];
      assign incoming_address_right[candidate][base] = incoming_address_i_b[candidate][base];
      parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
        .i_a(incoming_address_left[candidate][base]), .i_b(incoming_address_right[candidate][base]),
        .i_carry(incoming_address_carry[candidate]), .o_sum(incoming_address_sum[candidate][base]),
        .o_carry(unused_incoming_address_carry[candidate][base])
      );
    end
    for (genvar target = 0; target < 2; target++) begin : g_word_match
      logic [p_word_shift:0] low_sum;
      logic [31-p_word_shift:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry;
      assign low_sum = {1'b0, incoming_address_left[candidate][0][p_word_shift-1:0]} +
        {1'b0, incoming_address_right[candidate][0][p_word_shift-1:0]} +
        (p_word_shift+1)'(incoming_address_carry[candidate]);
      assign high_i_a = incoming_address_left[candidate][0][31:p_word_shift];
      assign high_i_b = incoming_address_right[candidate][0][31:p_word_shift];
      assign high_i_target = target == 0 ? word_addr[31:p_word_shift] : addr[31:p_word_shift];
      assign high_i_carry = low_sum[p_word_shift];
      add_equal #(.p_width(32-p_word_shift)) u_match (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(incoming_candidate_word_match[candidate][target])
      );
    end
  end
  for (genvar target = 0; target < 2; target++) begin : g_next_row_match
    logic [p_word_shift:0] low_sum;
    logic [31-p_word_shift:0] high_i_a, high_i_b, high_i_target;
    logic high_i_carry;
    assign low_sum = {1'b0, row_base_addr[p_word_shift-1:0]} +
      {1'b0, movement_i_b[0][p_word_shift-1:0]};
    assign high_i_a = row_base_addr[31:p_word_shift];
    assign high_i_b = movement_i_b[0][31:p_word_shift];
    assign high_i_target = target == 0 ? word_addr[31:p_word_shift] : addr[31:p_word_shift];
    assign high_i_carry = low_sum[p_word_shift];
    add_equal #(.p_width(32-p_word_shift)) u_match (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_i_carry), .o_equal(next_row_word_match[target])
    );
    assign incoming_window_word_match[target] = incoming_position_previous_row ? incoming_candidate_word_match[6][target] :
      incoming_position_forward_tap ? incoming_candidate_word_match[4][target] :
      incoming_position_backward_tap ? incoming_candidate_word_match[5][target] :
      window_next_addr[31:p_word_shift] == high_i_target;
    assign incoming_skip_word_match[target] = kx0_q != 16'd0 ?
      incoming_candidate_word_match[3][target] : incoming_candidate_word_match[2][target];
    assign incoming_advanced_word_match[target] = incoming_next_position_fast ? incoming_window_word_match[target] :
      incoming_next_tile_fast ? next_row_word_match[target] : incoming_skip_word_match[target];
  end

  // Configuration-time products leave only additions and bounds checks at
  // row and tap boundaries while the current word is being transferred.
  assign row_wrap = row_wrap_q;
  assign tap_wrap = tap_wrap_q;
  always_comb begin
    next_row_ix = $signed(bound_sum[0]);
    next_row_iy = $signed(bound_sum[1]);
    next_row_pixel=movement_o_sum[2];
    next_row_addr=movement_o_sum[0];
    next_row_group_base=movement_o_sum[1];
    // 有效图像坐标的高位必须全为零，低十六位再与图像尺寸比较。
    next_row_padding = !bound_valid[0] || !bound_valid[1];
    // 配置阶段保存卷积核末列，当前列判断不再经过加一进位。
    next_tap_ix = $signed(bound_sum[2]);
    next_tap_iy = $signed(bound_sum[3]);
    next_tap_pixel=movement_o_sum[4];
    next_tap_addr=movement_o_sum[3];
    next_tap_padding = !bound_valid[2] || !bound_valid[3];
  end

  // 配置和分块解码共用分组幂次检查，组合结果由原有控制周期接收。
  logic [15:0] stride_shape_i_value;
  logic stride_shape_o_valid;
  assign stride_shape_i_value = cfg.stride_h;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_stride_shape (
    .i_value(stride_shape_i_value),
    .o_valid(stride_shape_o_valid)
  );
  logic [31:0] pixel_shape_i_value;
  logic pixel_shape_o_valid;
  assign pixel_shape_i_value = cfg_pixel_bytes;
  onehot_check #(.p_width(32), .p_allow_zero(1'b0)) u_pixel_shape (
    .i_value(pixel_shape_i_value),
    .o_valid(pixel_shape_o_valid)
  );
  logic [15:0] group_shape_i_value;
  logic group_shape_o_valid, group_shape_check_o_valid;
  assign group_shape_i_value = cfg.group_c;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_group_shape (
    .i_value(group_shape_i_value),
    .o_valid(group_shape_check_o_valid)
  );
  logic [15:0] kernel_shape_i_value;
  logic kernel_shape_o_valid, kernel_shape_check_o_valid;
  assign kernel_shape_i_value = cfg.kernel_w;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_kernel_shape (
    .i_value(kernel_shape_i_value),
    .o_valid(kernel_shape_check_o_valid)
  );
  logic [15:0] output_shape_i_value;
  logic output_shape_o_valid, output_shape_check_o_valid;
  logic [4:0] output_width_shift;
  assign output_shape_i_value = cfg.output_w;
  onehot_check #(.p_width(16), .p_allow_zero(1'b0)) u_output_shape (
    .i_value(output_shape_i_value),
    .o_valid(output_shape_check_o_valid)
  );
  // 形状判断与配置同时保存，后续解码直接使用对应配置的寄存结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      group_shape_o_valid <= 1'b0;
      kernel_shape_o_valid <= 1'b0;
      output_shape_o_valid <= 1'b0;
      output_width_shift <= 5'd0;
    end else if (cfg_valid && cfg_ready) begin
      group_shape_o_valid <= group_shape_check_o_valid;
      kernel_shape_o_valid <= kernel_shape_check_o_valid;
      output_shape_o_valid <= output_shape_check_o_valid;
      output_width_shift <= power_shift({16'd0,cfg.output_w});
    end
  end
  function automatic logic [4:0] power_shift(input logic [31:0] value);
    logic [4:0] result;
    result=0;
    for (int b=0;b<32;b++) if (value[b]) result=5'(b);
    return result;
  endfunction
  // 配置准备阶段保存行偏移和限幅阈值，运行时的加法与范围判断并行。
  logic [16:0] retire_bias_q;
  logic [30:0] retire_scaled_last;
  logic [16:0] retire_compare_delta;
  logic [15:0] retire_compare_q;
  logic retire_all_bounded_q, retire_no_bound_q;
  logic prefetch_retire_pfa_q;

  assign retire_scaled_last = {15'd0, retire_last_row_q} << retire_shift_q;
  assign retire_compare_delta = {1'b0, retire_compare_q} - {1'b0, c.pad_top};
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      retire_bias_q <= 17'd0;
      retire_compare_q <= 16'd0;
      retire_all_bounded_q <= 1'b0;
      retire_no_bound_q <= 1'b0;
    end else begin
      if (cfg_prepare_phase == 2'd1) begin
        retire_bias_q <= {1'b0, c.pad_top} +
          (short_pixel_q ? (17'd1 << retire_shift_q) : 17'd0);
        // 准备期间复用最终阈值寄存器，先保存低位及高位范围分类。
        retire_compare_q <= retire_scaled_last[15:0];
        retire_all_bounded_q <= !(|retire_scaled_last[30:16]);
        retire_no_bound_q <= |retire_scaled_last[30:17];
      end
      if (cfg_prepare_phase == 2'd2) begin
        retire_compare_q <= retire_compare_delta[15:0];
        retire_all_bounded_q <= retire_all_bounded_q && retire_compare_delta[16];
        retire_no_bound_q <= retire_no_bound_q ||
          (!retire_all_bounded_q && !retire_compare_delta[16]);
      end
    end
  end

  // 预取输入选择随原状态转换保存，计算端口直接使用已寄存的一位选择。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) prefetch_retire_pfa_q <= 1'b0;
    else if (cfg_valid && cfg_ready) prefetch_retire_pfa_q <= 1'b0;
    else prefetch_retire_pfa_q <= prefetch_phase == 4'd2;
  end

  // 请求和预取各共用一个计算端口，全部结果仍在原请求接收周期使用。
  assign retirement_input[0] = REGISTER_CACHE_REQUEST ?
      (request_pending ? request_y_q : iy[15:0]) : request_y[15:0];
  assign retirement_input[1] = prefetch_retire_pfa_q ? pfa_y[15:0] : pf0_y[15:0];
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
    // 行偏移使用四位分组进位，移位使用缓存已有的接收寄存级。
    parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1)) u_row_bias (
      .i_a(retire_i_a), .i_b(retire_i_b), .i_carry(retire_i_carry),
      .o_sum(biased_row), .o_carry(unused_row_carry)
    );
    assign limit_reached = retire_all_bounded_q ||
      (!retire_no_bound_q && retirement_input[row_port] >= retire_compare_q);
    assign retire_payload_row = limit_reached ? {2'b0, retire_last_row_q} : biased_row;
    assign retire_payload_shift = limit_reached ? 4'd0 : retire_shift_q;
    // 元数据低十八位保存被移位数，随后四位保存移位量，第22位表示禁止释放。
    // 缓存接收寄存之后执行移位，高九位保留为零。
    assign retirement_result[row_port] =
        {9'd0, !retire_enabled_q, retire_payload_shift, retire_payload_row};
  end
  assign request_retire = retirement_result[0];

  // 位置解码使用已接受的描述符，快速请求的资格条件保证输入位置与保存位置相同。
  // 解码行尾在减去输出宽度之前检查模加法等式，与坐标结果并行。
  assign p_decode = p0;
  assign p_cache_select = 2'(p_decode >> CW);
  // 三个解码范围的末项检查并行进行，控制结果不等待计数器加一。
  assign decode_end_i_target[0] = {16'd0, c.output_w};
  assign decode_end_i_target[1] = {16'd0, c.group_c};
  assign decode_end_i_target[2] = {16'd0, c.kernel_w};
  for (genvar decode_dimension = 0; decode_dimension < 3; decode_dimension++) begin : g_decode_end
    logic [31:0] end_i_a, end_i_b, end_i_target;
    logic end_i_carry_in;
    logic end_o_equal;

    assign end_i_a = decode_inner;
    assign end_i_b = '0;
    assign end_i_target = decode_end_i_target[decode_dimension];
    assign end_i_carry_in = 1'b1;
    assign decode_end_o_equal[decode_dimension] = end_o_equal;
    add_equal #(.p_width(32)) u_end (
      .i_a(end_i_a), .i_b(end_i_b), .i_target(end_i_target),
      .i_carry_in(end_i_carry_in), .o_equal(end_o_equal)
    );
  end
  // 接收位置与历史位置的差值先保存，坐标解码只执行一次分组加法。
  always_ff @(posedge clk) begin
    if (tile_commit) p_history_delta_q <= committing_tile.position[15:0] - last_p[15:0];
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) p_wrap_target_q <= 16'd0;
    else if (cfg_valid && cfg_ready) p_wrap_target_q <= {cfg.output_w[14:0], 1'b0} - 16'd1;
  end
  assign p_delta = REGISTER_DESCRIPTOR ? p_history_delta_q : 16'(p_decode - last_p);
  parallel_prefix_add #(.p_width(17), .p_group_width(4), .p_preserve_groups(1'b1)) u_history_sum (
    .i_a({1'b0, last_x}), .i_b({1'b0, p_delta}), .i_carry(1'b0),
    .o_sum(p_sum), .o_carry(unused_p_sum_carry)
  );
  logic [17:0] history_reduce_i_a, history_reduce_i_b, history_reduce_o_sum;
  logic [17:0] history_reduce_generate;
  logic history_width_reached;
  logic unused_history_reduce_high;

  // 历史列、位置增量和输出宽度先压缩，减法不再依赖前一级完整和值。
  assign history_reduce_i_a = {2'b0, last_x} ^ {2'b0, p_delta} ^ ~{2'b0, c.output_w};
  assign history_reduce_generate = ({2'b0, last_x} & {2'b0, p_delta}) |
    (({2'b0, last_x} | {2'b0, p_delta}) & ~{2'b0, c.output_w});
  assign {unused_history_reduce_high, history_reduce_i_b} = {history_reduce_generate, 1'b1};
  parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1)) u_history_reduced (
    .i_a(history_reduce_i_a), .i_b(history_reduce_i_b), .i_carry(1'b0),
    .o_sum(history_reduce_o_sum), .o_carry(unused_p_sum_reduced_carry)
  );
  assign p_sum_reduced = history_reduce_o_sum[16:0];
  assign history_width_reached = !history_reduce_o_sum[17];
  // 行尾等式直接压缩位置差和历史列数，逐位比较与坐标加减并行。
  assign p_sum_wrap_i_a = last_x ^ p_decode[15:0] ^ ~last_p[15:0];
  assign p_sum_wrap_carry = (last_x & p_decode[15:0]) |
    ((last_x | p_decode[15:0]) & ~last_p[15:0]);
  assign {unused_p_sum_wrap_carry, p_sum_wrap_i_b} = {p_sum_wrap_carry, 1'b1};
  assign p_sum_wrap_i_target = p_wrap_target_q;
  assign p_sum_wrap_i_carry_in = 1'b0;
  add_equal #(.p_width(16), .p_use_lut(1'b0)) u_p_sum_wrap (
    .i_a(p_sum_wrap_i_a),
    .i_b(p_sum_wrap_i_b),
    .i_target(p_sum_wrap_i_target),
    .i_carry_in(p_sum_wrap_i_carry_in),
    .o_equal(p_sum_wrap_o_equal)
  );
  assign p_sum_last_i_a = p_sum_wrap_i_a;
  assign p_sum_last_i_b = p_sum_wrap_i_b;
  assign p_sum_last_i_target = last_output_col_q;
  assign p_sum_last_i_carry_in = 1'b0;
  add_equal #(.p_width(16), .p_use_lut(1'b0)) u_p_sum_last (
    .i_a(p_sum_last_i_a), .i_b(p_sum_last_i_b), .i_target(p_sum_last_i_target),
    .i_carry_in(p_sum_last_i_carry_in), .o_equal(p_sum_last_o_equal)
  );
  always_comb begin
    p_fast_valid=0;p_fast_y=0;p_fast_x=0;
    p_fast_wrap = c.output_w != 16'd0 && last_output_col_q == 16'd0;
    if (p_decode==0) p_fast_valid=1;
    else if (output_shape_o_valid) begin
      // 二次幂输出宽度通过移位和掩码直接得到行列坐标。
      p_fast_valid=1;p_fast_y=p_decode>>output_width_shift;
      p_fast_x=p_decode&{16'd0,last_output_col_q};
      p_fast_wrap=p_fast_x=={16'd0,last_output_col_q};
    end
    else if (p_cache_valid[p_cache_select] && p_cache_key[p_cache_select]==p_decode) begin
      p_fast_valid=1;p_fast_y=32'(p_cache_y[p_cache_select]);p_fast_x=32'(p_cache_x[p_cache_select]);
      p_fast_wrap = c.output_w != 16'd0 && p_cache_x[p_cache_select] == last_output_col_q;
    end else if (last_p_valid && p_decode>=last_p && p_decode<=last_p_limit) begin
      p_fast_valid=1;p_fast_y=32'(last_y);p_fast_x=32'(p_sum);
      // 模和值等于目标时，历史列数与目标的关系直接给出最高位进位。
      p_fast_wrap = c.output_w != 16'd0 &&
        ((p_sum_last_o_equal && last_x <= p_sum_last_i_target) ||
         (p_sum_wrap_o_equal && (!last_output_col_q[15] || last_x > p_sum_wrap_i_target)));
      if (history_width_reached) begin p_fast_x=32'(p_sum_reduced);p_fast_y=32'(last_y)+1;end
    end
  end

  // 像素索引的高十六位分别计算两种输入进位，末端只选择结果。
  assign incoming_pixel_delta = incoming_tap_wrap ? 32'($unsigned(tap_wrap_pixels)) : {16'd0, c.dilation_w};
  assign incoming_pixel_low = {1'b0, row_base_pixel[15:0]} + {1'b0, incoming_pixel_delta[15:0]};
  assign {unused_incoming_pixel_high_zero_carry, incoming_pixel_high_zero} =
    {1'b0, row_base_pixel[31:16]} + {1'b0, incoming_pixel_delta[31:16]};
  assign {unused_incoming_pixel_high_one_carry, incoming_pixel_high_one} =
    {1'b0, row_base_pixel[31:16]} + {1'b0, incoming_pixel_delta[31:16]} + 17'd1;
  assign incoming_pixel_next = {
    incoming_pixel_low[16] ? incoming_pixel_high_one : incoming_pixel_high_zero,
    incoming_pixel_low[15:0]};

  // 三种坐标的边界关系并行计算，描述符只选择已经完成的填充判断。
  assign incoming_step_ix = $signed(bound_sum[4]);
  assign incoming_wrap_ix = $signed(bound_sum[5]);
  assign incoming_wrap_iy = $signed(bound_sum[6]);
  assign incoming_base_padding = (|row_base_ix[COORD_W-1:16]) || (|row_base_iy[COORD_W-1:16]) ||
    row_base_ix[15:0] >= c.input_w || row_base_iy[15:0] >= c.input_h;
  assign incoming_step_padding = !bound_valid[4] || (|row_base_iy[COORD_W-1:16]) ||
    row_base_iy[15:0] >= c.input_h;
  assign incoming_wrap_padding = !bound_valid[5] || !bound_valid[6];

  // 组内范围按描述符列数拆分，低位进位只选择已完成的高位关系。
  if (TILE_COUNT_W < 16) begin : g_incoming_group_range
    localparam int p_high_w = 16 - TILE_COUNT_W;
    logic [TILE_COUNT_W:0] column_end_low;
    logic high_before, high_equal, low_within, remaining_wrap;
    logic [p_high_w-1:0] high_next_i_a, high_next_i_b, high_next_i_target;
    logic high_next_i_carry_in, high_next_o_equal;

    assign column_end_low = {1'b0, ch0_q[TILE_COUNT_W-1:0]} + {1'b0, cols_q};
    assign high_before = ch0_q[15:TILE_COUNT_W] < c.group_c[15:TILE_COUNT_W];
    assign high_equal = ch0_q[15:TILE_COUNT_W] == c.group_c[15:TILE_COUNT_W];
    assign low_within = column_end_low[TILE_COUNT_W-1:0] <= c.group_c[TILE_COUNT_W-1:0];
    assign remaining_wrap = (!high_before && !high_equal) ||
      (high_equal && ch0_q[TILE_COUNT_W-1:0] > c.group_c[TILE_COUNT_W-1:0]);
    assign high_next_i_a = ch0_q[15:TILE_COUNT_W];
    assign high_next_i_b = '0;
    assign high_next_i_carry_in = 1'b1;
    assign high_next_i_target = c.group_c[15:TILE_COUNT_W];
    add_equal #(.p_width(p_high_w), .p_use_lut(1'b0)) u_high_next (
      .i_a(high_next_i_a),
      .i_b(high_next_i_b),
      .i_carry_in(high_next_i_carry_in),
      .i_target(high_next_i_target),
      .o_equal(high_next_o_equal)
    );
    // 低位进位和高位关系并行合并，范围结果参与快速接收判断。
    assign incoming_group_fits = remaining_wrap ||
      (high_before && (!column_end_low[TILE_COUNT_W] || !high_next_o_equal || low_within)) ||
      (high_equal && !column_end_low[TILE_COUNT_W] && low_within);
  end else begin : g_incoming_group_range_wide
    assign incoming_group_fits = 32'(cols_q) <= 32'(c.group_c) - ch0;
  end

  // 新分块列数只参与低位加法，高位大小和相邻关系并行计算。
  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range
    logic [15:0] first_channel;
    logic [16:0] requested_columns;

    assign first_channel = source == 0 ? window_next_ch : ch0_q;
    assign requested_columns = tile_cols == '0 ? 17'(SIZE) : 17'(tile_cols);
    if (TILE_COUNT_W < 16) begin : g_split
      localparam int p_high_w = 16 - TILE_COUNT_W;
      logic [TILE_COUNT_W:0] column_end_low;
      logic high_before, high_equal, low_within;
      logic [p_high_w-1:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry, high_o_equal;

      assign column_end_low = {1'b0, first_channel[TILE_COUNT_W-1:0]} +
        (TILE_COUNT_W+1)'(requested_columns);
      assign high_i_a = first_channel[15:TILE_COUNT_W];
      assign high_i_b = '0;
      assign high_i_target = c.group_c[15:TILE_COUNT_W];
      assign high_i_carry = 1'b1;
      assign high_before = high_i_a < high_i_target;
      assign high_equal = high_i_a == high_i_target;
      assign low_within = column_end_low[TILE_COUNT_W-1:0] <= c.group_c[TILE_COUNT_W-1:0];
      add_equal #(.p_width(p_high_w)) u_high_next (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(high_o_equal)
      );
      assign incoming_tile_group_fits[source] =
        (high_before && (!column_end_low[TILE_COUNT_W] || !high_o_equal || low_within)) ||
        (high_equal && !column_end_low[TILE_COUNT_W] && low_within);
    end else begin : g_wide
      assign incoming_tile_group_fits[source] =
        {1'b0, first_channel} + requested_columns <= {1'b0, c.group_c};
    end
  end

  assign incoming_tap_wrap = incoming_tap_wrap_q;

  // 五位位置乘以 11 后右移五位，精确得到除三的商。
  // 余数保留低两位；模四运算中减去三倍商等价于加上商。
  logic [8:0] q_decode_scaled;
  logic [3:0] q_decode_o_quotient;
  logic [1:0] q_decode_o_remainder;
  assign q_decode_scaled = {1'b0, q0[4:0], 3'b000} +
    {3'b000, q0[4:0], 1'b0} + {4'b0000, q0[4:0]};
  assign q_decode_o_quotient = q_decode_scaled[8:5];
  assign q_decode_o_remainder = q0[1:0] + q_decode_o_quotient[1:0];
  assign current_q_div3 = {1'b0, q_decode_o_quotient};
  assign current_q_remainder = {q0[15:5], 3'b000, q_decode_o_remainder};

  // 描述符字段分组比较，步长和低位进位使用同一个接收条件。
  logic [2:0][32:0] incoming_compare_a, incoming_compare_b;
  logic [2:0][10:0] incoming_part_equal;
  logic [2:0][1:0] incoming_group_equal;
  assign incoming_compare_a[0] = {1'b0, tile_p0};
  assign incoming_compare_a[1] = {1'b0, tile_q0};
  assign incoming_compare_a[2] = {1'b0, tile_q0};
  assign incoming_compare_b[0] = {1'b0, p0};
  assign incoming_compare_b[1] = {1'b0, q0};
  assign incoming_compare_b[2] = next_group_q;
  for (genvar value = 0; value < 3; value++) begin : g_incoming_compare
    for (genvar part = 0; part < 11; part++) begin : g_part
      assign incoming_part_equal[value][part] =
        incoming_compare_a[value][3*part +: 3] == incoming_compare_b[value][3*part +: 3];
    end
    assign incoming_group_equal[value][0] = &incoming_part_equal[value][5:0];
    assign incoming_group_equal[value][1] = &incoming_part_equal[value][10:6];
  end
  assign incoming_position_equal = incoming_group_equal[0];
  assign incoming_q_equal = &incoming_group_equal[1];
  assign incoming_delta = incoming_q_equal ? 32'd0 :
    (incoming_tap_wrap ? tap_wrap_bytes : tap_step_bytes);
  assign incoming_word_i_carry_in = !incoming_q_equal &&
    (incoming_tap_wrap ? incoming_wrap_low_sum[p_word_shift] : incoming_step_low_sum[p_word_shift]);
  // 三列卷积在边缘跳过一个填充位置时，两个核位置的增量仍可直接递推。
  // 核位置匹配直接检查各位进位一致性，描述符比较不经过串行加法器。
  assign incoming_tap_match_i_a[0] = next_group_q;
  assign incoming_tap_match_i_a[1] = {1'b0, window_next_q};
  assign incoming_tap_match_i_a[2] = {1'b0, tile_q0};
  assign incoming_tap_match_i_a[3] = {1'b0, tile_q0};
  assign incoming_tap_match_i_b[0] = {17'd0, c.group_c};
  assign incoming_tap_match_i_b[1] = {17'd0, c.group_c};
  assign incoming_tap_match_i_b[2] = {17'd0, c.group_c};
  assign incoming_tap_match_i_b[3] = {16'd0, c.group_c, 1'b0};
  assign incoming_tap_match_i_target[0] = {1'b0, tile_q0};
  assign incoming_tap_match_i_target[1] = {1'b0, tile_q0};
  assign incoming_tap_match_i_target[2] = {1'b0, window_next_q};
  assign incoming_tap_match_i_target[3] = {1'b0, window_next_q};
  assign incoming_tap_match_i_carry_in = '0;
  for (genvar match_index = 0; match_index < 4; match_index++) begin : g_incoming_tap_match
    add_equal #(.p_width(33)) u_match (
      .i_a(incoming_tap_match_i_a[match_index]),
      .i_b(incoming_tap_match_i_b[match_index]),
      .i_target(incoming_tap_match_i_target[match_index]),
      .i_carry_in(incoming_tap_match_i_carry_in[match_index]),
      .o_equal(incoming_tap_match_o_equal[match_index])
    );
  end
  // 空间分块起点保留三十二位模加结果，溢出行为与描述符地址宽度一致。
  assign incoming_tile_match_i_a = p0;
  assign incoming_tile_match_i_b = 32'(rows_q);
  assign incoming_tile_match_i_target = tile_p0;
  assign incoming_tile_match_i_carry_in = 1'b0;
  add_equal #(.p_width(32)) u_incoming_tile_match (
    .i_a(incoming_tile_match_i_a), .i_b(incoming_tile_match_i_b),
    .i_target(incoming_tile_match_i_target), .i_carry_in(incoming_tile_match_i_carry_in),
    .o_equal(incoming_tile_match_o_equal)
  );
  assign incoming_skip_tap = c.kernel_w == 16'd3 && incoming_tap_match_o_equal[0];
  assign incoming_q_fast = incoming_q_equal || (&incoming_group_equal[2]) || incoming_skip_tap;
  // 坐标资格与单行条件提前合并，晚到的组范围保持单级接收选择。
  assign incoming_fast_i_flags[0] = c.windowed && row_base_valid && coordinate_address_valid;
  assign incoming_fast_i_flags[1] = rows_q == TILE_COUNT_W'(1) && tile_rows == RW'(1);
  assign incoming_fast_i_flags[2] = incoming_group_fits;
  assign incoming_fast_i_flags[4:3] = incoming_position_equal;
  assign incoming_fast_i_flags[5] = incoming_q_fast;
  assign incoming_same_position_fast = CACHE_POLICY == 3 && (&incoming_fast_i_flags);
  // 相邻空间位置可从同一核行的前后一个有效位置开始，列边界只调整水平步长。
  assign incoming_position_same_tap = tile_q0 == window_next_q;
  assign incoming_position_forward_tap = window_forward_allowed_q &&
      incoming_tap_match_o_equal[1];
  assign incoming_position_backward_tap = window_backward_allowed_q &&
      incoming_tap_match_o_equal[2];
  // 三列卷积从顶部边缘进入下一输出行时，首个有效核位置向前移动两个位置。
  assign incoming_position_previous_row = window_previous_allowed_q &&
      incoming_tap_match_o_equal[3];
  assign incoming_next_position_fast = CACHE_POLICY == 3 && c.windowed && window_next_valid &&
      tile_rows == RW'(1) && tile_p0 == window_next_p &&
      (incoming_position_same_tap || incoming_position_forward_tap ||
       incoming_position_backward_tap || incoming_position_previous_row) &&
      incoming_tile_group_fits[0];
  // 连续空间分块继承末行的下一坐标，归约起点变化时继续执行通用解码。
  assign incoming_next_tile_fast = CACHE_POLICY == 3 && c.windowed && !geometry_tile &&
      row_base_valid && coordinate_address_valid && tile_q0 == q0 &&
      incoming_tile_match_o_equal &&
      incoming_tile_group_fits[1];
  assign incoming_fast = incoming_same_position_fast || incoming_next_position_fast || incoming_next_tile_fast;

  // 位置递增和保存值的匹配并行计算，更新条件直接使用进位一致性比较。
  assign next_position_i_b = 32'd0;
  assign next_position_i_carry = 1'b1;
  add_equal #(.p_width(32)) u_next_position_match (
    .i_a(p0), .i_b(next_position_i_b), .i_target(window_next_p),
    .i_carry_in(next_position_i_carry), .o_equal(next_position_o_equal)
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_next_position (
    .i_a(p0), .i_b(next_position_i_b), .i_carry(next_position_i_carry),
    .o_sum(next_position), .o_carry(unused_next_position_carry)
  );

  // 每个空间位置的首个有效卷积核位置准备下一空间坐标，并保留通道分组和核坐标。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      window_next_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      window_next_valid <= 1'b0;
    end else if (rows_q == TILE_COUNT_W'(1) && row_base_valid &&
                 coordinate_address_valid && (state[$clog2(FETCH)] || state[$clog2(WAIT_WORD)] ||
                 state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) &&
                 (!window_next_valid || !next_position_o_equal)) begin
      window_next_valid <= next_position < position_count;
      window_next_p <= next_position;
      window_next_q <= q0;
      window_next_tap <= tap0;
      window_next_ch <= ch0_q;
      window_next_kx <= kx0_q;
      window_forward_allowed_q <= kx0_q < last_kernel_col_q;
      window_backward_allowed_q <= kx0_q != 16'd0;
      window_previous_allowed_q <= c.kernel_w == 16'd3 && kx0_q == 16'd0 && ky0_q != 16'd0;
      window_next_ky <= ky0_q;
      window_next_x <= row_wrap ? 16'd0 : ox_q + 16'd1;
      window_next_y <= row_wrap ? oy_q + 16'd1 : oy_q;
      window_next_last_col <= row_wrap ? last_output_col_q==16'd0 : row_next_o_equal;
      window_next_ix <= next_row_ix;
      window_next_iy <= next_row_iy;
      window_next_pixel <= next_row_pixel;
      window_next_addr <= next_row_addr;
      window_next_group_base <= next_row_group_base;
      window_next_padding <= next_row_padding;
      window_next_channel_range <= group_range_next[1];
    end
  end
  logic [6:0][COORD_W-1:0] candidate_coordinate_i_a, candidate_coordinate_i_b;
  logic [6:0][COORD_W-1:0] candidate_coordinate_sum;
  logic [6:0] candidate_coordinate_carry, unused_candidate_coordinate_carry;
  assign candidate_coordinate_i_a = {row_base_iy, row_base_ix, row_base_iy, row_base_ix, window_next_iy, window_next_ix, window_next_ix};
  assign candidate_coordinate_i_b[0] = COORD_W'(c.dilation_w);
  assign candidate_coordinate_i_b[1] = ~COORD_W'(c.dilation_w);
  assign candidate_coordinate_i_b[2] = ~COORD_W'(c.dilation_h);
  assign candidate_coordinate_i_b[3] = tap_pair_dx;
  assign candidate_coordinate_i_b[4] = COORD_W'(c.dilation_h);
  assign candidate_coordinate_i_b[5] = COORD_W'(c.dilation_w) << 1;
  assign candidate_coordinate_i_b[6] = '0;
  assign candidate_coordinate_carry = 7'b0000110;
  for (genvar source = 0; source < 7; source++) begin : g_candidate_coordinate
    logic [COORD_W-1:0] sum_i_a, sum_i_b;
    assign sum_i_a = candidate_coordinate_i_a[source];
    assign sum_i_b = candidate_coordinate_i_b[source];
    parallel_prefix_add #(.p_width(COORD_W), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(sum_i_a), .i_b(sum_i_b), .i_carry(candidate_coordinate_carry[source]),
      .o_sum(candidate_coordinate_sum[source]), .o_carry(unused_candidate_coordinate_carry[source])
    );
  end

  logic [6:0] candidate_coordinate_valid;
  for (genvar axis = 0; axis < 7; axis++) begin : g_candidate_bound
    logic [15:0] coordinate_limit;
    logic [8:0] low_byte, high_zero, high_one;
    logic low_before, high_zero_before, high_one_before;
    logic high_zero_equal, high_one_equal, high_carry, high_equal;
    logic [COORD_W-17:0] high_i_a, high_i_b, high_i_target;
    logic low_carry;

    // 高字节的两种进位结果及比较并行完成，高位仅检查模加结果是否为零。
    assign coordinate_limit = axis == 2 || axis == 4 || axis == 6 ? c.input_h : c.input_w;
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
    assign high_i_a = candidate_coordinate_i_a[axis][COORD_W-1:16];
    assign high_i_b = candidate_coordinate_i_b[axis][COORD_W-1:16];
    assign high_i_target = '0;
    add_equal #(.p_width(COORD_W-16)) u_high_zero (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_carry), .o_equal(high_equal)
    );
    assign candidate_coordinate_valid[axis] = high_equal &&
      (low_carry ? high_one_before : high_zero_before);
  end

  logic incoming_kx_last;
  logic [3:0][15:0] incoming_kernel_i_a, incoming_kernel_i_target;
  logic [15:0] incoming_kernel_i_b;
  logic incoming_kernel_i_carry;
  logic [3:0] incoming_kernel_o_equal;
  logic incoming_window_kx_last, incoming_skip_kx_last, incoming_base_kx_last;
  assign incoming_kernel_i_a = {last_kernel_col_q, kx0_q, last_kernel_col_q, window_next_kx};
  assign incoming_kernel_i_target = {kx0_q, last_kernel_col_q, window_next_kx, last_kernel_col_q};
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
  assign incoming_base_kx_last = kx0_q == last_kernel_col_q;
  assign incoming_window_kx_last = incoming_position_previous_row ? last_kernel_col_q == 16'd1 :
    incoming_position_forward_tap ? incoming_kernel_o_equal[0] :
    incoming_position_backward_tap ? incoming_kernel_o_equal[1] : window_next_kx == last_kernel_col_q;
  assign incoming_skip_kx_last = kx0_q != 16'd0 ? incoming_kernel_o_equal[3] : last_kernel_col_q == 16'd2;
  assign incoming_kx_last = incoming_next_position_fast ? incoming_window_kx_last :
    incoming_next_tile_fast ? incoming_base_kx_last : incoming_skip_tap ? incoming_skip_kx_last :
    !incoming_q_equal ? (incoming_tap_wrap ? last_kernel_col_q == 16'd0 : incoming_kernel_o_equal[2]) :
    incoming_base_kx_last;

  // 各候选坐标和填充状态独立计算，晚到的描述符仅选择计算结果。
  // 高位检查保留完整的有符号坐标范围，低十六位比较有效图像尺寸。
  assign window_forward_ix = $signed(candidate_coordinate_sum[0]);
  assign window_backward_ix = $signed(candidate_coordinate_sum[1]);
  assign window_previous_iy = $signed(candidate_coordinate_sum[2]);
  assign window_forward_padding = !candidate_coordinate_valid[0] ||
    (|window_next_iy[COORD_W-1:16]) || window_next_iy[15:0] >= c.input_h;
  assign window_backward_padding = !candidate_coordinate_valid[1] ||
    (|window_next_iy[COORD_W-1:16]) || window_next_iy[15:0] >= c.input_h;
  assign window_previous_padding = !candidate_coordinate_valid[0] || !candidate_coordinate_valid[2];
  assign incoming_skip_ix = $signed(kx0_q != 16'd0 ? candidate_coordinate_sum[3] : candidate_coordinate_sum[5]);
  assign incoming_skip_iy = $signed(kx0_q != 16'd0 ? candidate_coordinate_sum[4] : candidate_coordinate_sum[6]);
  // 两种跳核坐标并行检查边界，核列状态只选择最终的填充标志。
  assign incoming_skip_padding = kx0_q != 16'd0 ?
    (!candidate_coordinate_valid[3] || !candidate_coordinate_valid[4]) :
    (!candidate_coordinate_valid[5] || !candidate_coordinate_valid[6]);
  // 同核位置保留已保存的填充标志，其余候选维持前一行、前向、后向的选择次序。
  assign window_shift_padding = incoming_position_same_tap ? window_next_padding :
    incoming_position_previous_row ? window_previous_padding :
    incoming_position_forward_tap ? window_forward_padding : window_backward_padding;

  always_comb begin
    incoming_tap=tap0;incoming_ch=ch0;incoming_kx=kx0;incoming_ky=ky0;
    incoming_ix=row_base_ix;incoming_iy=row_base_iy;
    incoming_pixel=row_base_pixel;incoming_addr=row_base_addr;incoming_group_base=row_group_base;
    incoming_padding=incoming_base_padding;
    if (incoming_next_position_fast) begin
      incoming_tap=window_next_tap;incoming_ch={16'd0,window_next_ch};
      incoming_kx={16'd0,window_next_kx};incoming_ky={16'd0,window_next_ky};
      incoming_ix=window_next_ix;incoming_iy=window_next_iy;
      incoming_pixel=window_next_pixel;incoming_addr=window_next_addr;
      incoming_group_base=window_next_group_base;incoming_padding=window_shift_padding;
      if (incoming_position_previous_row) begin
        incoming_tap=window_next_tap-32'd2;
        incoming_kx=32'd1;incoming_ky={16'd0,window_next_ky}-32'd1;
        incoming_ix=window_forward_ix;
        incoming_iy=window_previous_iy;
        incoming_pixel=window_next_pixel-tap_pair_pixels;
        incoming_addr=incoming_address_sum[6][0];
        incoming_group_base=incoming_address_sum[6][1];
      end else if (incoming_position_forward_tap) begin
        incoming_tap=window_next_tap+32'd1;incoming_kx={16'd0,window_next_kx}+32'd1;
        incoming_ix=window_forward_ix;
        incoming_pixel=window_next_pixel+32'(c.dilation_w);
        incoming_addr=incoming_address_sum[4][0];
        incoming_group_base=incoming_address_sum[4][1];
      end else if (incoming_position_backward_tap) begin
        incoming_tap=window_next_tap-32'd1;incoming_kx={16'd0,window_next_kx}-32'd1;
        incoming_ix=window_backward_ix;
        incoming_pixel=window_next_pixel-32'(c.dilation_w);
        incoming_addr=incoming_address_sum[5][0];
        incoming_group_base=incoming_address_sum[5][1];
      end
    end else if (incoming_next_tile_fast) begin
      incoming_ix=next_row_ix;incoming_iy=next_row_iy;
      incoming_pixel=next_row_pixel;incoming_addr=next_row_addr;
      incoming_group_base=next_row_group_base;incoming_padding=next_row_padding;
    end else if (incoming_skip_tap) begin
      incoming_tap=tap0+32'd2;
      incoming_ix=incoming_skip_ix;incoming_iy=incoming_skip_iy;
      incoming_padding=incoming_skip_padding;
      if (kx0_q!=16'd0) begin
        incoming_kx=kx0-32'd1;incoming_ky=ky0+32'd1;
        incoming_pixel=row_base_pixel+tap_pair_pixels;
        incoming_addr=incoming_address_sum[3][0];
        incoming_group_base=incoming_address_sum[3][1];
      end else begin
        incoming_kx=32'd2;
        incoming_pixel=row_base_pixel+(32'(c.dilation_w)<<1);
        incoming_addr=incoming_address_sum[2][0];
        incoming_group_base=incoming_address_sum[2][1];
      end
    end else if (!incoming_q_equal) begin
      incoming_tap=tap0+1;
      if (incoming_tap_wrap) begin
        incoming_kx=0;incoming_ky=ky0+1;
        incoming_ix=incoming_wrap_ix;
        incoming_iy=incoming_wrap_iy;
        incoming_pixel=incoming_pixel_next;
        incoming_addr=incoming_address_sum[1][0];incoming_group_base=incoming_address_sum[1][1];
        incoming_padding=incoming_wrap_padding;
      end else begin
        incoming_kx=kx0+1;
        incoming_ix=incoming_step_ix;
        incoming_pixel=incoming_pixel_next;
        incoming_addr=incoming_address_sum[0][0];incoming_group_base=incoming_address_sum[0][1];
        incoming_padding=incoming_step_padding;
      end
    end
  end

  // 每个字节并行判断地址进位，最后合并四段结果。
  for (genvar byte_index = 0; byte_index < 4; byte_index++) begin : g_cfg_address_carry
    assign cfg_address_generate[byte_index] =
      c.input_base[8*byte_index+:8] > ~cfg_tensor_product[8*byte_index+:8];
    assign cfg_address_propagate[byte_index] =
      c.input_base[8*byte_index+:8] == ~cfg_tensor_product[8*byte_index+:8];
  end
  assign cfg_address_overflow = cfg_address_generate[3] ||
    (cfg_address_propagate[3] && cfg_address_generate[2]) ||
    (cfg_address_propagate[3] && cfg_address_propagate[2] && cfg_address_generate[1]) ||
    (cfg_address_propagate[3] && cfg_address_propagate[2] && cfg_address_propagate[1] && cfg_address_generate[0]);

  // Configuration products cross register boundaries before overflow checks.
  always_comb begin
    cfg_basic_valid=cfg.input_h!=0 && cfg.input_w!=0 && cfg.input_c!=0 &&
      cfg.group_c!=0 && cfg.kernel_h!=0 && cfg.kernel_w!=0 &&
      cfg.output_h!=0 && cfg.output_w!=0 && cfg.stride_h!=0 && cfg.stride_w!=0 &&
      cfg.dilation_h!=0 && cfg.dilation_w!=0 &&
      (17'(cfg.group_offset)+17'(cfg.group_c)<=17'(cfg.input_c));
    if (cfg.input_s16) cfg_basic_valid=cfg_basic_valid && cfg.input_offset==0 && !cfg.input_base[0];
    else cfg_basic_valid=cfg_basic_valid && $signed(cfg.input_offset)>=-127 && $signed(cfg.input_offset)<=128;
    cfg_input_bytes={15'd0,cfg_tensor_product};
    cfg_red={16'd0,cfg_reduction_product};
    cfg_positions=cfg_position_product;
    cfg_ok=cfg_basic_saved && cfg_tensor_product[48:32]==0 &&
      cfg_reduction_product[47:32]==0 && !cfg_address_overflow;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      cfg_prepare_phase<=0;
      cfg_basic_saved<=0;
    end else if (cfg_valid && cfg_ready) begin
      cfg_prepare_phase<=1;
      cfg_basic_saved<=cfg_basic_valid;
      cfg_input_hw<=32'(cfg.input_h)*32'(cfg.input_w);
      cfg_kernel_taps<=32'(cfg.kernel_h)*32'(cfg.kernel_w);
      cfg_position_product<=32'(cfg.output_h)*32'(cfg.output_w);
    end else case (cfg_prepare_phase)
      1: begin
        cfg_tensor_product<=(49'(cfg_input_hw)*49'(c.input_c))<<c.input_s16;
        cfg_reduction_product<=48'(cfg_kernel_taps)*48'(c.group_c);
        cfg_prepare_phase<=2;
      end
      2: cfg_prepare_phase<=0;
      default: ;
    endcase
  end
  // 配置接收并行检查各组状态，缓存就绪参与末级条件。
  logic [2:0][5:0] cfg_idle_groups;
  logic [2:0] cfg_idle_group_clear;
  assign cfg_idle_groups[0] = {request_pending, !state[$clog2(IDLE)], 4'b0000};
  assign cfg_idle_groups[1] = {cfg_prepare_phase, address_step_phase, prefetch_phase[1:0]};
  assign cfg_idle_groups[2] = {prefetch_phase[3:2], pred_busy, pred_cfg_busy, pred_cfg_pending, cache_cfg_pending};
  for (genvar group_index = 0; group_index < 3; group_index++) begin : g_cfg_idle_group
    assign cfg_idle_group_clear[group_index] = !(|cfg_idle_groups[group_index]);
  end
  assign cfg_ready = (&cfg_idle_group_clear) && cache_cfg_ready && !cache_hint_pending && !tile_prepared_valid;
  assign finishing_tile=wr_valid && wr_ready && wr_last;
  // 描述符就绪的静态条件共用，配置有效只参与最终接收选择。
  assign tile_ready_context = (state[$clog2(IDLE)] || finishing_tile) && cfg_prepare_phase==0 && configured && !error &&
                              !pred_busy && !pred_cfg_busy && !pred_cfg_pending && !cache_cfg_pending &&
                              !cache_hint_pending && address_step_phase==0;
  assign tile_ready = tile_ready_context && !cfg_valid && (!tile_prepared_valid || tile_commit);
  assign busy = !cfg_ready;
  assign wr_valid = state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)] ||
                    (state[$clog2(WAIT_WORD)] && cache_rsp_valid && !cache_rsp_error);
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);
  // 行末标志与行号同时保存，当前传输完成只合并列末判断。
  assign {unused_row_index_carry, next_row_idx} = {1'b0, row_idx} + (TILE_COUNT_W+1)'(1);
  assign next_row_last = 32'(next_row_idx) + 32'd1 == 32'(rows_q);
  assign wr_last = row_last_q && chunk_reaches_end;

  assign pred_start = state[$clog2(ADDRESS)] && geometry_tile && col_idx==0 &&
    q_current<{1'b0,reduction_len} && ix>=0 && iy>=0 &&
    ix<$signed(COORD_W'(c.input_w)) && iy<$signed(COORD_W'(c.input_h)) &&
    !pred_busy && !cache_hint_pending;
  // 预测器的位置输入提前按四位分组进位，后续可直接执行分块移位。
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_predictor_position (
    .i_a(p0), .i_b(32'(row_idx)), .i_carry(1'b0),
    .o_sum(predictor_position), .o_carry(unused_predictor_position_carry)
  );
  generate if (SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0) begin : g_next_use
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
  if (LANES <= 8 && LANES <= p_cache_read_bytes) begin : g_short_word_advance
    for (genvar step = 0; step <= LANES; step++) begin : g_step
      logic [p_word_shift+1:0] offset_sum;
      logic [31-p_word_shift:0] match_i_b;
      logic saved_word_equal;
      assign offset_sum = {2'b0, addr[p_word_shift-1:0]} +
        (c.input_s16 ? (p_word_shift+2)'(2*step) : (p_word_shift+2)'(step));
      logic boundary_s8, boundary_s16;
      // 固定步长直接与字内剩余字节比较，边界条件不经过地址求和。
      if (step == 0) begin : g_no_advance
        assign boundary_s8 = 1'b0;
        assign boundary_s16 = 1'b0;
      end else begin : g_positive_advance
        if (step >= p_cache_read_bytes) begin : g_s8_full_word
          assign boundary_s8 = 1'b1;
        end else begin : g_s8_remaining
          assign boundary_s8 = addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-step);
        end
        if (2*step >= p_cache_read_bytes) begin : g_s16_full_word
          assign boundary_s16 = 1'b1;
        end else begin : g_s16_remaining
          assign boundary_s16 = addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-2*step);
        end
      end
      assign step_word_boundary[step] = c.input_s16 ? boundary_s16 : boundary_s8;
      assign match_i_b = (32-p_word_shift)'(offset_sum[p_word_shift+1:p_word_shift]);
      add_equal #(.p_width(32-p_word_shift)) u_word_match (
        .i_a(addr[31:p_word_shift]), .i_b(match_i_b), .i_carry_in(1'b0),
        .i_target(word_addr[31:p_word_shift]), .o_equal(saved_word_equal)
      );
      assign step_saved_hit[step] = state[$clog2(WAIT_WORD)] ? !step_word_boundary[step] :
        word_valid && word_addr[p_word_shift-1:0] == '0 && saved_word_equal;
    end
    assign word_boundary = |(chunk_selected & step_word_boundary);
    assign next_byte_saved_hit = |(chunk_selected & step_saved_hit);
  end else begin : g_wide_word_advance
    assign word_boundary = byte_offset_sum >= (p_word_shift+2)'(p_cache_read_bytes);
    assign next_byte_saved_hit = state[$clog2(WAIT_WORD)] ?
      next_byte_addr[31:p_word_shift] == addr[31:p_word_shift] :
      word_valid && word_addr == {next_byte_addr[31:p_word_shift], {p_word_shift{1'b0}}};
    assign step_word_boundary = '0;
    assign step_saved_hit = '0;
  end
  // 连续读取只在耗尽当前缓存字时发起，下一请求地址独立于传输数量编码。
  assign stream_request_addr[p_word_shift-1:0] = '0;
  parallel_prefix_add #(.p_width(32-p_word_shift), .p_group_width(4), .p_preserve_groups(1'b1)) u_stream_request_word (
    .i_a(addr[31:p_word_shift]), .i_b((32-p_word_shift)'(1)), .i_carry(1'b0),
    .o_sum(stream_request_addr[31:p_word_shift]), .o_carry(unused_stream_request_carry)
  );
  if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_stream_remaining
    logic [LANES-1:0] column_after_lane, active_after_lane;
    for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
      assign column_after_lane[lane] = TILE_COUNT_W'(lane+1) < col_remaining;
      assign active_after_lane[lane] = TILE_COUNT_W'(lane+1) < active_remaining;
    end
    assign column_after_chunk = col_remaining != '0 && (&(~chunk_lane_allowed | column_after_lane));
    assign active_after_chunk = active_remaining != '0 && (&(~chunk_lane_allowed | active_after_lane));
  end else begin : g_stream_remaining_wide
    assign column_after_chunk = TILE_COUNT_W'(chunk_count) < col_remaining;
    assign active_after_chunk = TILE_COUNT_W'(chunk_count) < active_remaining;
  end
  assign stream_context=state[$clog2(STREAM)] || state[$clog2(WAIT_WORD)];
  assign stream_next_request=wr_valid && wr_ready && !state[$clog2(ZERO_STREAM)] &&
    column_after_chunk && active_after_chunk &&
    group_after_chunk && word_boundary;
  // 字命中标志与当前地址同时保存，请求有效条件只读取一位状态。
  assign current_word_hit = (REGISTER_CACHE_REQUEST || REGISTER_DESCRIPTOR) ? addr_word_hit_q :
    word_valid && word_addr == {addr[31:p_word_shift], {p_word_shift{1'b0}}};
  assign next_tap_saved_hit = state[$clog2(WAIT_WORD)] ? next_word_o_equal :
    word_valid && word_addr == {next_tap_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  // 通道地址的字命中直接比较加法等式，完整地址和匹配结果并行计算。
  logic [p_word_shift:0] channel_word_low_sum;
  logic channel_word_equal;
  assign channel_word_low_sum = {1'b0, group_base_addr[p_word_shift-1:0]} +
    {1'b0, channel_byte_offset[p_word_shift-1:0]};
  add_equal #(.p_width(32-p_word_shift), .p_use_lut(1'b0)) u_channel_word (
    .i_a(group_base_addr[31:p_word_shift]),
    .i_b((32-p_word_shift)'(channel_byte_offset >> p_word_shift)),
    .i_carry_in(channel_word_low_sum[p_word_shift]),
    .i_target(word_addr[31:p_word_shift]), .o_equal(channel_word_equal)
  );
  assign channel_saved_hit = word_valid && word_addr[p_word_shift-1:0] == '0 && channel_word_equal;
  // 当前行最后一拍被接收时，下一行的地址已经由独立加法器准备完成。
  assign next_row_word_hit = state[$clog2(WAIT_WORD)] ? next_row_word_match[1] :
      word_valid && word_addr[p_word_shift-1:0] == '0 && next_row_word_match[0];
  // 分段模式先保存下一行地址，再由 FETCH 发起读取。
  assign next_row_request = !REGISTER_ROW_ADDRESS && wr_valid && wr_ready && chunk_reaches_end && !row_last_q &&
      row_base_valid && !geometry_tile && !next_row_padding && !next_row_word_hit;
  assign incoming_word_hit = incoming_next_position_fast || incoming_next_tile_fast || incoming_skip_tap ?
    (finishing_tile && state[$clog2(WAIT_WORD)] ? incoming_advanced_word_match[1] :
      word_valid && word_addr[p_word_shift-1:0] == '0 && incoming_advanced_word_match[0]) :
    (finishing_tile && state[$clog2(WAIT_WORD)] ? incoming_live_word_o_equal :
      (word_valid && word_addr[p_word_shift-1:0] == '0 && incoming_word_o_equal));
  assign incoming_request=!REGISTER_CACHE_REQUEST && !REGISTER_DESCRIPTOR && tile_valid && tile_ready && incoming_fast && !incoming_padding &&
    !incoming_word_hit && tile_rows!=0 && 32'(tile_rows)<=SIZE && 32'(tile_cols)<=SIZE &&
    tile_q_before_end && tile_rows_in_range;
  assign cache_req_valid = incoming_request ||
                           (state[$clog2(FETCH)] && !(current_word_hit)) ||
                           stream_next_request || next_row_request;
  assign incoming_context=!REGISTER_DESCRIPTOR && tile_valid && incoming_fast &&
    (state[$clog2(IDLE)] || ((state[$clog2(WAIT_WORD)] || state[$clog2(STREAM)] || state[$clog2(ZERO_STREAM)]) && wr_last));
  assign cache_req_addr=!REGISTER_CACHE_REQUEST && incoming_context ? incoming_addr : next_row_request ? next_row_addr :
      stream_context ? stream_request_addr : addr;
  assign cache_rsp_ready = state[$clog2(WAIT_WORD)] && (wr_ready || cache_rsp_error);
  assign cache_config_valid = cache_cfg_pending && !pred_cfg_pending && !pred_cfg_busy;
  // The registered trigger consumes the accepted configuration. Cache setup
  // waits until the predictor has produced its new eligibility flag.
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) pred_cfg_pending<=1'b0;
    else if (cfg_prepare_phase==2)
      pred_cfg_pending<=cfg_ok && SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0;
    else pred_cfg_pending<=1'b0;
  end
  always_ff @(posedge clk) begin
    if (cfg_valid && cfg_ready) predictor_cfg_r<=cfg_sched_r;
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cache_cfg_pending <= 1'b0;
    else if (cfg_valid && cfg_ready) cache_cfg_pending <= 1'b0;
    else if (cfg_prepare_phase==2) cache_cfg_pending <= cfg_ok;
    else if (cache_config_valid && cache_cfg_ready) cache_cfg_pending <= 1'b0;
  end
  // 可选请求寄存用于时序划分；直接模式复用缓存输入寄存级，连续命中每周期传输。
  assign request_bypass = state[$clog2(FETCH)] && !request_pending;
  assign cache_port_valid = REGISTER_CACHE_REQUEST ?
      (request_pending || (request_bypass && !(current_word_hit))) : cache_req_valid;
  assign cache_req_ready = REGISTER_CACHE_REQUEST ?
      (request_bypass ? cache_port_ready : (!request_pending || cache_port_ready)) : cache_port_ready;
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
    else if (cache_req_ready) request_pending <= REGISTER_CACHE_REQUEST && cache_req_valid && !request_bypass;
  end
  always_ff @(posedge clk) begin
    if (!request_pending || cache_port_ready) begin
      request_addr_q <= cache_req_addr;
      request_geometry_q <= geometry_tile;
      request_event_first_q <= geometry_tile && cache_req_addr[3:0]==0;
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
    .p_defer_retire_shift(CACHE_POLICY == 3)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cache_config_valid),.cfg_ready(cache_cfg_ready),
    .cfg_base(c.input_base),.cfg_bytes(tensor_bytes),.cfg_bypass(c.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(c.windowed),.cfg_prefetch_enable(c.prefetch_enable),
    .req_valid(cache_port_valid),.req_ready(cache_port_ready),
    .req_addr(REGISTER_CACHE_REQUEST ? (request_pending ? request_addr_q : addr) : cache_req_addr),
    .req_geometry(request_pending ? request_geometry_q : geometry_tile),
    .req_event_first(request_pending ? request_event_first_q :
      (geometry_tile && (REGISTER_CACHE_REQUEST ? addr[3:0] == 4'd0 : cache_req_addr[3:0] == 4'd0))),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .req_window_index_valid(request_pending ? request_index_valid_q : req_index_valid),
    .req_window_index(REGISTER_CACHE_REQUEST ? (request_pending ? request_index_q : current_req_index) : req_index),
    .req_window_epoch(REGISTER_CACHE_REQUEST ? (request_pending ? request_epoch_q : current_req_epoch) : req_epoch),
    .req_window_retire(request_retire),
    .req_window_progress(REGISTER_CACHE_REQUEST ? (request_pending ? request_progress_q : oy) : request_output_y),
    .prefetch_valid(pf_valid),.prefetch_ready(pf_ready),.prefetch_addr(pf_addr),
    .prefetch_window_index_valid(pf_index_valid),.prefetch_window_index(pf_index),
    .prefetch_window_epoch(pf_epoch),.prefetch_window_retire(
      (!pf1_coordinate_valid && pf1_fragment) ? pf1_ref_retire : pf1_retire),
    .prefetch_next_fragment(pf1_fragment),
    .prefetch_ref_valid(1'b1),.prefetch_ref_addr(pf1_ref_addr),
    .prefetch_ref_index_valid(pf1_ref_index_valid),.prefetch_ref_index(pf1_ref_index),
    .prefetch_ref_epoch(pf1_ref_epoch),
    .rsp_valid(cache_rsp_valid),.rsp_ready(cache_rsp_ready),
    .rsp_data(cache_rsp_data),.rsp_error(cache_rsp_error),
    .arvalid,.arready,.araddr,.arlen,.arsize,.arburst,.rvalid,.rready,.rdata,.rresp,.rlast
  );
  // 递增比较并行处理符号、宽位溢出及低十六位边界。
  assign ix_step_below_limit = (ix == p_coord_max) ||
      (ix[COORD_W-1] && ((c.input_w != 16'd0) || ix != -35'sd1)) ||
      ((c.input_w != 16'd0) && !(|ix[COORD_W-1:16]) && ix[15:0] < last_input_col_q);

  // 输入横坐标的完整三十五位增量使用分组进位。
  parallel_prefix_add #(.p_width(COORD_W), .p_group_width(4), .p_preserve_groups(1'b1)) u_input_x_increment (
    .i_a(ix), .i_b(COORD_W'(1)), .i_carry(1'b0),
    .o_sum(ix_increment), .o_carry(unused_ix_increment_carry)
  );

  // 各种通道来源并行计算组内范围，接收边沿只选择相应标志。
  assign group_range_channel[0] = 16'd0;
  assign group_range_channel[1] = ch0_q;
  assign group_range_channel[2] = q0[15:0] & last_group_channel_q;
  assign group_range_channel[3] = current_q_remainder;
  assign group_range_channel[4] = 16'(decode_inner);
  assign group_range_channel[5] = next_channel;

  logic [16:0] group_end_i_a, group_end_i_b, group_end_i_target;
  logic group_end_i_carry_in, group_end_o_equal;

  // 传输到组末的条件直接检查加法等式，保留第十七位的回绕语义。
  assign group_end_i_a = {1'b0, ch_q};
  assign group_end_i_b = 17'(chunk_count);
  assign group_end_i_target = {1'b0, c.group_c};
  assign group_end_i_carry_in = 1'b0;
  if (LANES <= 8) begin : g_group_end_by_lane
    logic [LANES:0] step_o_equal, selected_end;

    // 各种通道数的组末关系提前计算，当前周期只选择最后有效通道。
    for (genvar step = 0; step <= LANES; step++) begin : g_step
      // 范围标志与通道坐标同拍保存，相邻边界的转换直接表示剩余长度。
      if (step == 0) begin : g_zero_remaining
        assign step_o_equal[step] = !group_range_q[0];
      end else begin : g_remaining_boundary
        assign step_o_equal[step] = group_range_q[step-1] && !group_range_q[step];
      end
      if (step == 0) begin : g_no_lane
        assign selected_end[step] = !(|chunk_lane_allowed) && step_o_equal[step];
      end else if (step < LANES) begin : g_has_later_lane
        assign selected_end[step] = chunk_lane_allowed[step-1] &&
            !(|chunk_lane_allowed[LANES-1:step]) && step_o_equal[step];
      end else begin : g_final_lane
        assign selected_end[step] = chunk_lane_allowed[step-1] && step_o_equal[step];
      end
    end
    assign group_end_o_equal = |selected_end;
  end else begin : g_group_end_wide
    add_equal #(.p_width(17), .p_use_lut(1'b0)) u_group_end (
      .i_a(group_end_i_a), .i_b(group_end_i_b), .i_target(group_end_i_target),
      .i_carry_in(group_end_i_carry_in), .o_equal(group_end_o_equal)
    );
  end

  if (LANES <= 8) begin : g_short_group_lane
    logic [p_saved_group_lanes-1:0][15:0] cfg_group_last;
    logic cfg_has_channel;
    (* keep = 1 *) logic [p_saved_group_lanes-1:0] cfg_short_group;

    assign cfg_has_channel = cfg.group_c != ch_q;
    for (genvar offset = 0; offset < p_saved_group_lanes; offset++) begin : g_cfg_offset
      logic [16:0] match_i_a, match_i_b, match_i_target;
      logic match_i_carry, match_o_equal;
      assign match_i_a = {1'b0, ch_q};
      assign match_i_b = 17'(offset + 1);
      assign match_i_target = {1'b0, cfg.group_c};
      assign match_i_carry = 1'b0;
      add_equal #(.p_width(17)) u_match (
        .i_a(match_i_a), .i_b(match_i_b), .i_target(match_i_target),
        .i_carry_in(match_i_carry), .o_equal(match_o_equal)
      );
      // 扩展位保留通道加偏移的溢出，范围匹配使用并行进位等式。
      assign cfg_group_last[offset] = cfg.group_c - 16'(offset + 1);
      always_comb begin
        case (^{cfg.group_c, ch_q})
          1'b0, 1'b1: cfg_short_group[offset] = match_o_equal;
          // 含未知位的输入使用定宽减法，保持比较结果的四态传播。
          default: cfg_short_group[offset] = cfg.group_c >= 16'(offset + 1) &&
              ch_q == cfg_group_last[offset];
        endcase
      end
    end
    for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_cfg_lane
      if (lane == 0) begin : g_any_channel
        assign group_range_cfg[lane] = cfg_has_channel;
      end else begin : g_remaining
        assign group_range_cfg[lane] = cfg_has_channel && !(|cfg_short_group[lane-1:0]);
      end
    end
    for (genvar source = 0; source < 6; source++) begin : g_source
      if (source == 5) begin : g_advancing_channel
        logic [p_saved_group_lanes:0][15:0] step_i_target;
        logic [LANES:0][p_saved_group_lanes:0] boundary_match, range_for_step;
        logic [11:0] high_i_a, high_i_b;
        logic [3:0] low_i_a;
        logic low_i_carry_in;
        assign high_i_a = ch_q[15:4];
        assign high_i_b = 12'd0;
        assign low_i_a = ch_q[3:0];
        assign low_i_carry_in = 1'b0;
        assign step_i_target[0] = c.group_c;
        for (genvar boundary = 1; boundary <= p_saved_group_lanes; boundary++) begin : g_target
          assign step_i_target[boundary] = group_last_channels_q[boundary-1];
        end
        for (genvar boundary = 0; boundary <= p_saved_group_lanes; boundary++) begin : g_boundary
          logic [11:0] high_i_target;
          logic [3:0] low_i_target;
          logic high_i_carry_in, high_o_equal, high_gate;
          assign high_i_target = step_i_target[boundary][15:4];
          assign low_i_target = step_i_target[boundary][3:0];
          assign high_i_carry_in = ch_q[3] && !step_i_target[boundary][3];
          add_equal #(.p_width(12)) u_high (
            .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
            .i_carry_in(high_i_carry_in), .o_equal(high_o_equal)
          );
          if (boundary == 0) begin : g_group_end
            assign high_gate = high_o_equal;
          end else begin : g_short_group
            assign high_gate = high_o_equal && group_at_least_q[boundary];
          end
          for (genvar step = 0; step <= LANES; step++) begin : g_step
            logic [3:0] low_i_b;
            logic low_o_equal;
            assign low_i_b = 4'(step);
            add_equal #(.p_width(4)) u_low (
              .i_a(low_i_a), .i_b(low_i_b), .i_target(low_i_target),
              .i_carry_in(low_i_carry_in), .o_equal(low_o_equal)
            );
            assign boundary_match[step][boundary] = high_gate && low_o_equal;
          end
        end
        for (genvar step = 0; step <= LANES; step++) begin : g_step_range
          for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
            assign range_for_step[step][lane] = !(|boundary_match[step][lane:0]);
          end
        end
        logic [LANES:0] step_select;
        assign step_select[0] = !(|chunk_lane_allowed);
        for (genvar step = 1; step <= LANES; step++) begin : g_selected_step
          if (step == LANES) begin : g_last
            assign step_select[step] = chunk_lane_allowed[step-1];
          end else begin : g_has_later_lane
            assign step_select[step] = chunk_lane_allowed[step-1] && !(|chunk_lane_allowed[LANES-1:step]);
          end
        end
        // 最后有效通道形成独热选择，各种步长的范围按位并行归并。
        always_comb begin
          group_range_next[source] = '0;
          for (int step = 0; step <= LANES; step++)
            group_range_next[source] |= {(p_saved_group_lanes+1){step_select[step]}} & range_for_step[step];
        end
      end else begin : g_saved_channel
        logic group_has_channel;
        logic [p_saved_group_lanes-1:0] short_group;
        assign group_has_channel = c.group_c != group_range_channel[source];
        for (genvar boundary = 1; boundary <= p_saved_group_lanes; boundary++) begin : g_boundary
          assign short_group[boundary-1] = group_at_least_q[boundary] &&
            group_range_channel[source] == group_last_channels_q[boundary-1];
        end
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
          if (lane == 0) begin : g_any_channel
            assign group_range_next[source][lane] = group_has_channel;
          end else begin : g_remaining
            assign group_range_next[source][lane] = group_has_channel && !(|short_group[lane-1:0]);
          end
        end
      end
    end
    // 范围标志与通道索引在同一边沿保存，输出和后续请求使用寄存结果。
    assign group_lane_allowed = group_range_q[LANES-1:0];
    assign group_after_chunk = group_range_q[0] &&
      (&(~chunk_lane_allowed | group_range_q[LANES:1]));
  end else if (LANES <= 32768) begin : g_group_lane_range
    assign group_range_cfg = '0;
    assign group_range_next = '0;
    logic [LANES:0] group_range;
    assign group_lane_allowed = group_range[LANES-1:0];
    // 常量步数的范围同时计算，通道掩码只参与末级并行归并。
    assign group_after_chunk = group_range[0] && (&(~chunk_lane_allowed | group_range[LANES:1]));
    logic high_before_end, high_at_end, high_before_end_by_one, remaining_wrap;
    if (p_group_low_w == 2) begin : g_split_high_compare
      // 两段高位关系并行计算，最高一段不相等时直接确定整体顺序。
      assign high_before_end = ch_q[15:9] < c.group_c[15:9] ||
        (ch_q[15:9] == c.group_c[15:9] && ch_q[8:2] < c.group_c[8:2]);
    end else begin : g_general_high_compare
      assign high_before_end = ch_q[15:p_group_low_w] < c.group_c[15:p_group_low_w];
    end
    assign high_at_end = ch_q[15:p_group_low_w] == c.group_c[15:p_group_low_w];
    assign high_before_end_by_one = ch_q[15:p_group_low_w] == group_high_minus_one_q;
    assign remaining_wrap = (!high_before_end && !high_at_end) ||
        (high_at_end && ch_q[p_group_low_w-1:0] > c.group_c[p_group_low_w-1:0]);
    for (genvar lane = 0; lane <= LANES; lane++) begin : g_lane
      logic [p_group_low_w:0] lane_last_low;
      logic low_before_end;
      if (p_group_low_w == 2) begin : g_two_bit_offset
        // 两位偏移按位生成进位与和值，通道范围检查直接使用三位结果。
        if (lane == 0) begin : g_zero
          assign lane_last_low = {1'b0, ch_q[1:0]};
        end else if (lane == 1) begin : g_one
          assign lane_last_low = {(&ch_q[1:0]), ch_q[1] ^ ch_q[0], ~ch_q[0]};
        end else if (lane == 2) begin : g_two
          assign lane_last_low = {ch_q[1], ~ch_q[1], ch_q[0]};
        end else begin : g_three
          assign lane_last_low = {(|ch_q[1:0]), ch_q[1] ^ ~ch_q[0], ~ch_q[0]};
        end
      end else begin : g_general_offset
        assign lane_last_low = {1'b0, ch_q[p_group_low_w-1:0]} + (p_group_low_w+1)'(lane);
      end
      assign low_before_end = lane_last_low[p_group_low_w-1:0] < c.group_c[p_group_low_w-1:0];
      assign group_range[lane] = remaining_wrap ||
          (high_before_end && (!lane_last_low[p_group_low_w] || !high_before_end_by_one || low_before_end)) ||
          (high_at_end && !lane_last_low[p_group_low_w] && low_before_end);
    end
  end else begin : g_group_lane_range_wide
    assign group_range_cfg = '0;
    assign group_range_next = '0;
    assign group_after_chunk = 17'(chunk_count) < group_remaining;
    for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
      assign group_lane_allowed[lane] = 17'(lane) < group_remaining;
    end
  end

  // 每条通道直接检查字内偏移，常量边界同时覆盖八位和十六位输入。
  for (genvar lane = 0; lane < LANES; lane++) begin : g_word_lane
    (* keep = 1 *) logic allowed_s8, allowed_s16;
    // 字内范围只有少量地址位，按位比较使常量边界独立于地址加法的进位。
    function automatic logic before_word_end(
      input logic [p_word_shift-1:0] value,
      input logic [p_word_shift:0] limit
    );
      logic [p_word_shift:0] extended_value;
      logic equal_prefix, lower_value;
      extended_value = {1'b0, value};
      equal_prefix = 1'b1;
      lower_value = 1'b0;
      for (int bit_index = p_word_shift; bit_index >= 0; bit_index--) begin
        lower_value |= equal_prefix && !extended_value[bit_index] && limit[bit_index];
        equal_prefix &= extended_value[bit_index] == limit[bit_index];
      end
      case (^{value, limit})
        1'b0, 1'b1: before_word_end = lower_value;
        default: before_word_end = 1'bx;
      endcase
    endfunction
    if (lane < p_cache_read_bytes) begin : g_s8
      assign allowed_s8 = before_word_end(addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-lane));
    end else begin : g_s8_empty
      assign allowed_s8 = 1'b0;
    end
    if (lane < p_cache_read_bytes/2) begin : g_s16
      assign allowed_s16 = before_word_end(addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-1-2*lane));
    end else begin : g_s16_empty
      assign allowed_s16 = 1'b0;
    end
    assign word_lane_allowed[lane] = c.input_s16 ? allowed_s16 : allowed_s8;
    // 数据资格与列末位置并行计算，列计数只参与末级匹配。
    assign chunk_data_allowed[lane] = (!narrow_output || lane<NARROW_LANES) &&
      (past_active_q || (group_lane_allowed[lane] && TILE_COUNT_W'(lane)<active_remaining)) &&
      ((!state[$clog2(STREAM)] && !state[$clog2(WAIT_WORD)]) || word_lane_allowed[lane]);
    if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_complete_column
      always_comb begin
        case (^col_remaining)
          1'b0, 1'b1: chunk_end_lane[lane] = chunk_data_allowed[lane] &&
            col_remaining == TILE_COUNT_W'(lane+1);
          default: chunk_end_lane[lane] = chunk_lane_allowed[lane] &&
            col_remaining == TILE_COUNT_W'(lane+1);
        endcase
      end
    end else begin : g_wrapped_column
      assign chunk_end_lane[lane] = chunk_lane_allowed[lane] &&
        col_remaining == TILE_COUNT_W'(lane+1);
    end
  end
  if (TILE_COUNT_W >= CHUNK_COUNT_W) begin : g_direct_chunk_end
    // 末通道可写即可完成当前行，无需等待通道数编码后再次比较。
    assign chunk_reaches_end = col_remaining == '0 || (|chunk_end_lane);
  end else begin : g_narrow_chunk_end
    assign chunk_reaches_end = TILE_COUNT_W'(chunk_count) == col_remaining;
  end

  // 偏移高字节的相邻值共用计算，晚到的字节选择仅经过低字节加法和末级选择。
  assign {unused_offset_high_add_carry, offset_high_plus_one} = {1'b0, c.input_offset[15:8]} + 9'd1;
  assign {unused_offset_high_sub_carry, offset_high_minus_one} = {1'b0, c.input_offset[15:8]} - 9'd1;
  for (genvar data_lane = 0; data_lane < LANES; data_lane++) begin : g_signed_byte_offset
    assign selected_s8_byte[data_lane] = 8'(selected_word >> (data_lane * 8));
    // 低字节和值与进位独立求解，进位直接比较输入字节与偏移补数。
    assign corrected_s8_low[data_lane][7:0] = selected_s8_byte[data_lane] + c.input_offset[7:0];
    assign corrected_s8_low[data_lane][8] = selected_s8_byte[data_lane] > ~c.input_offset[7:0];
    assign corrected_s8_high[data_lane] = selected_s8_byte[data_lane][7] ?
      (corrected_s8_low[data_lane][8] ? c.input_offset[15:8] : offset_high_minus_one) :
      (corrected_s8_low[data_lane][8] ? offset_high_plus_one : c.input_offset[15:8]);
    assign corrected_s8_value[data_lane] = {corrected_s8_high[data_lane], corrected_s8_low[data_lane][7:0]};
  end
  assign stream_word = state[$clog2(WAIT_WORD)] ? cache_rsp_data : word_buf;

  always_comb begin
    group_remaining={1'b0,c.group_c}-{1'b0,ch_q};
    chunk_count = '0;
    for (int lane=0;lane<LANES;lane++) begin
      // 描述符选择写入宽度；缓存字仍保留完整读取宽度供后续拍使用。
      chunk_lane_allowed[lane] = chunk_data_allowed[lane] && TILE_COUNT_W'(lane)<col_remaining;
      if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
    end
  end

  // 字节移位仅选择当前自然地址分组内的有效数据，字尾由通道掩码限制。
  assign selected_word = stream_word >> (8*addr[p_word_shift-1:0]);

  // 输出掩码直接归并后续通道资格，保持最高有效通道之前的所有位置有效。
  for (genvar output_lane = 0; output_lane < LANES; output_lane++) begin : g_output_mask
    assign wr_mask[output_lane] = |chunk_lane_allowed[LANES-1:output_lane];
  end
  always_comb begin
    for (int l=0;l<LANES;l++) begin
      wr_data[l]=0;
      if ((state[$clog2(STREAM)] || state[$clog2(WAIT_WORD)]) && wr_mask[l]) begin
        if (c.input_s16) wr_data[l]=$signed(16'(selected_word>>(l*16)));
        else wr_data[l]=$signed(corrected_s8_value[l]);
      end
    end
  end

  logic [LINE_BYTES:0] cfg_line_threshold, cfg_line_select;
  assign cfg_pixel_bytes = 32'(cfg.input_c) << cfg.input_s16;
  assign cfg_line_threshold[0] = 1'b1;
  for (genvar count = 1; count <= LINE_BYTES; count++) begin : g_line_threshold
    // 两种元素宽度分别与常量比较，输入位宽选择只作用于最终标志。
    assign cfg_line_threshold[count] = cfg.input_s16 ?
      32'(cfg.input_c) <= 32'(((LINE_BYTES-1)/count)/2) :
      32'(cfg.input_c) <= 32'((LINE_BYTES-1)/count);
  end
  for (genvar count = 0; count <= LINE_BYTES; count++) begin : g_line_select
    if (count == LINE_BYTES) begin : g_last
      assign cfg_line_select[count] = cfg_line_threshold[count];
    end else begin : g_has_next
      assign cfg_line_select[count] = cfg_line_threshold[count] && !cfg_line_threshold[count+1];
    end
  end
  logic [31:0] cfg_base_step;
  (* keep = 1 *) logic [31:0] cfg_stride_pf_step, cfg_dilation_pf_step;
  logic [31:0] cfg_selected_pf_step;
  assign cfg_base_step = cfg.kernel_w == 16'd1 ? 32'(cfg.stride_w) : 32'(cfg.dilation_w);
  // 两种步长独立计算行预读距离，卷积核宽度只选择最终结果。
  always_comb begin
    cfg_line_pixels = 32'd0;
    cfg_stride_pf_step = 32'd0;
    cfg_dilation_pf_step = 32'd0;
    cfg_selected_pf_step = 32'd0;
    for (int count = 0; count <= LINE_BYTES; count++) begin
      cfg_line_pixels |= {32{cfg_line_select[count]}} & 32'(count+1);
      cfg_stride_pf_step |= {32{cfg_line_select[count]}} &
        (32'(cfg.stride_w) < 32'(count+1) ? 32'(count+1) : 32'(cfg.stride_w));
      cfg_dilation_pf_step |= {32{cfg_line_select[count]}} &
        (32'(cfg.dilation_w) < 32'(count+1) ? 32'(count+1) : 32'(cfg.dilation_w));
      cfg_selected_pf_step |= {32{cfg_line_select[count]}} &
        (cfg_base_step < 32'(count+1) ? 32'(count+1) : cfg_base_step);
    end
    case (cfg.kernel_w == 16'd1)
      1'b0: cfg_pf_step = cfg_dilation_pf_step;
      1'b1: cfg_pf_step = cfg_stride_pf_step;
      // 未知选择条件保持逐位合并后再比较的四态结果。
      default: cfg_pf_step = cfg_selected_pf_step;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      pixel_bytes<=0;pf_step_base<=1;
      retire_enabled_q<=0;short_pixel_q<=0;retire_shift_q<=0;retire_last_row_q<=0;
      window_index_valid_q<=0;window_index_shift_q<=0;
      second_last_row_q<=0;last_output_col_q<=0;second_last_col_q<=0;
      last_kernel_col_q <= 16'd0;
      last_input_col_q <= 16'hffff;
      group_high_minus_one_q <= '1;
      last_group_channel_q <= 16'hffff;
      group_minus_two_q <= 16'hfffe;
      group_minus_three_q <= 16'hfffd;
      group_minus_four_q <= 16'hfffc;
      kernel_width_valid_q <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      pixel_bytes<=cfg_pixel_bytes;pf_step_base<=cfg_pf_step;
      retire_enabled_q<=stride_shape_o_valid;
      short_pixel_q<=cfg_pixel_bytes<LINE_BYTES;
      window_index_valid_q<=cfg.windowed && cfg.input_base[$clog2(LINE_BYTES)-1:0]==0 &&
        ((cfg_pixel_bytes>=LINE_BYTES && (cfg_pixel_bytes&(LINE_BYTES-1))==0) ||
         (pixel_shape_o_valid && cfg_pixel_bytes<LINE_BYTES));
      // 短像素只检查缓存行范围内的位，最高有效位直接选择移位数。
      if (LINE_BYTES > 0 && (LINE_BYTES & (LINE_BYTES - 1)) == 0) begin
        window_index_shift_q <= 5'd0;
        if (cfg_pixel_bytes < LINE_BYTES) begin
          window_index_shift_q <= 5'($clog2(LINE_BYTES));
          for (int bit_index = 1; bit_index < $clog2(LINE_BYTES); bit_index++) begin
            if (cfg_pixel_bytes[bit_index])
              window_index_shift_q <= 5'($clog2(LINE_BYTES) - bit_index);
          end
        end
      end else begin
        window_index_shift_q <= cfg_pixel_bytes < LINE_BYTES ?
          power_shift(32'(LINE_BYTES)) - power_shift(cfg_pixel_bytes) : 5'd0;
      end
      retire_shift_q<=4'(power_shift(32'(cfg.stride_h)));
      retire_last_row_q<=cfg.output_h-16'd1;
      second_last_row_q<=cfg.output_h-16'd2;
      last_output_col_q<=cfg.output_w-16'd1;second_last_col_q<=cfg.output_w-16'd2;
      last_kernel_col_q <= cfg.kernel_w - 16'd1;
      last_input_col_q <= cfg.input_w - 16'd1;
      group_high_minus_one_q <= cfg.group_c[15:p_group_low_w] - p_group_high_w'(1);
      last_group_channel_q <= cfg.group_c - 16'd1;
      group_minus_two_q <= cfg.group_c - 16'd2;
      group_minus_three_q <= cfg.group_c - 16'd3;
      group_minus_four_q <= cfg.group_c - 16'd4;
      kernel_width_valid_q <= cfg.kernel_w != 16'd0;
    end
  end

  assign epoch_i_a[0] = {16'd0, window_next_ch};
  assign epoch_i_a[1] = {16'd0, ch0_q};
  assign epoch_i_a[2] = ch;
  assign stream_epoch_xor = {16'd0, c.group_offset} ^ ch ^ 32'(chunk_count);
  assign stream_epoch_carry = (({16'd0, c.group_offset} & ch) |
    ({16'd0, c.group_offset} & 32'(chunk_count)) | (ch & 32'(chunk_count))) << 1;
  assign epoch_i_a[3] = stream_epoch_xor;
  assign epoch_i_a[4] = pfa_channel;
  assign epoch_i_b[0] = {16'd0, c.group_offset};
  assign epoch_i_b[1] = {16'd0, c.group_offset};
  assign epoch_i_b[2] = {16'd0, c.group_offset};
  assign epoch_i_b[3] = stream_epoch_carry;
  assign epoch_i_b[4] = {16'd0, c.group_offset};
  assign epoch_i_carry = 1'b0;
  for (genvar candidate = 0; candidate < 5; candidate++) begin : g_epoch_candidate
    if (candidate == 3 && LANES <= 8) begin : g_stream_steps
      logic [LANES:0][17:0] step_sum;
      logic [17:0] selected_sum;
      for (genvar step = 0; step <= LANES; step++) begin : g_step
        logic [17:0] sum_i_a, sum_i_b;
        logic unused_sum_carry;
        assign sum_i_a = {2'b0, c.group_offset} ^ {2'b0, ch_q} ^ 18'(step);
        assign sum_i_b = (({2'b0, c.group_offset} & {2'b0, ch_q}) |
          (({2'b0, c.group_offset} | {2'b0, ch_q}) & 18'(step))) << 1;
        parallel_prefix_add #(.p_width(18), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
          .i_a(sum_i_a), .i_b(sum_i_b), .i_carry(1'b0),
          .o_sum(step_sum[step]), .o_carry(unused_sum_carry)
        );
      end
      always_comb begin
        selected_sum = '0;
        for (int step = 0; step <= LANES; step++)
          selected_sum |= {18{chunk_selected[step]}} & step_sum[step];
      end
      assign epoch_o_sum[candidate] = {14'd0, selected_sum};
      assign unused_epoch_carry[candidate] = 1'b0;
    end else begin : g_general
      parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
        .i_a(epoch_i_a[candidate]), .i_b(epoch_i_b[candidate]), .i_carry(epoch_i_carry),
        .o_sum(epoch_o_sum[candidate]), .o_carry(unused_epoch_carry[candidate])
      );
    end
  end
  assign stream_channel_i_a = ch;
  assign stream_channel_i_b = 32'(chunk_count);
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_stream_channel (
    .i_a(stream_channel_i_a), .i_b(stream_channel_i_b), .i_carry(epoch_i_carry),
    .o_sum(stream_channel_full), .o_carry(unused_stream_channel_carry)
  );

  // 当前项与新描述符分别完成索引移位和纪元运算，描述符有效条件只控制末级选择。
  assign unused_incoming_epoch_carry = 1'b0;
  assign incoming_epoch_channel = incoming_next_position_fast ? epoch_o_sum[0] : epoch_o_sum[1];
  assign incoming_req_index = short_pixel_q ? incoming_pixel >> window_index_shift_q : incoming_pixel;
  assign incoming_req_epoch = short_pixel_q ? 32'd0 :
    (incoming_epoch_channel << c.input_s16) >> $clog2(LINE_BYTES);
  // 预读上下文在第一阶段准备纵向增量，第二阶段并行保存两种行坐标。
  // 第三阶段仅按横坐标是否跨行选择结果，保持原有预读输出周期。
  assign pf_y_step = pf_stream_lookahead || c.kernel_h == 16'd1 ? c.stride_h : c.dilation_h;
  assign pf_y_delta = pf_stream_lookahead && c.stride_h == 16'd1 && c.dilation_h == 16'd1 ?
    $signed({1'b0, c.kernel_h}) - 17'sd1 - $signed({1'b0, pfa_kernel_y}) : 17'sd0;
  assign pf_y_wrap_delta = 18'(pf_y_delta) + $signed({2'b0, pf_y_step});
  assign pf_prepare_i_a = {pfa_kernel_x, 32'(pfa_y), 32'(pfa_y)};
  assign pf_prepare_i_b = {pf_distance_q, 32'(pf_y_wrap_delta_q), 32'(pf_y_delta_q)};
  assign pf_prepare_i_carry = 1'b0;
  for (genvar source = 0; source < 3; source++) begin : g_prefetch_prepare
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(pf_prepare_i_a[source]), .i_b(pf_prepare_i_b[source]), .i_carry(pf_prepare_i_carry),
      .o_sum(pf_prepare_o_sum[source]), .o_carry(unused_pf_prepare_carry[source])
    );
  end

  // 下一预读横坐标先完成分组求和，边界选择不串接完整进位。
  logic [31:0] prefetch_next_x;
  logic unused_prefetch_x_carry;
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_x (
    .i_a(32'(pfa_x)), .i_b(pf_step_q), .i_carry(1'b0),
    .o_sum(prefetch_next_x), .o_carry(unused_prefetch_x_carry)
  );

  // 较大通道数按缓存行预测后续像素，提前保存新进入卷积窗口的输入行。
  assign pf_stream_lookahead = c.windowed && c.input_c >= 16'd16;
  always_comb begin
    request_y=!REGISTER_CACHE_REQUEST && incoming_context ? incoming_iy : next_row_request ? next_row_iy : iy;
    request_output_y=!REGISTER_CACHE_REQUEST && incoming_context ?
      (incoming_next_position_fast ? {16'd0, window_next_y} :
       incoming_next_tile_fast ? (row_wrap ? oy+32'd1 : oy) : p_fast_y) :
      next_row_request && row_wrap ? oy+32'd1 : oy;
    req_index_valid=window_index_valid_q;
    req_index=!REGISTER_CACHE_REQUEST && incoming_context ? incoming_req_index : next_row_request ?
      (short_pixel_q ? next_row_pixel>>window_index_shift_q : next_row_pixel) : current_req_index;
    req_epoch=!REGISTER_CACHE_REQUEST && incoming_context ? incoming_req_epoch : next_row_request ?
      (short_pixel_q ? 32'd0 : (epoch_o_sum[1]<<c.input_s16)>>$clog2(LINE_BYTES)) :
      stream_next_request ? (short_pixel_q ? 32'd0 :
        (epoch_o_sum[3]<<c.input_s16)>>$clog2(LINE_BYTES)) : current_req_epoch;
    pf_step=pf_step_q;
    pf_distance=pf_distance_q;
    pf_x=prefetch_next_x;pf_y=pf_y_base_q;
    if (pf_x>=32'(c.input_w)) begin
      // 跨越输入行时保留横向余量，并预测下一输出行使用的同一核位置。
      pf_x=pf_stream_lookahead ? pf_x-32'(c.input_w) : 32'd0;
      pf_y=pf_y_wrapped_q;
    end
    // 小通道片段按核行预测，换核行时保存相应的输入横坐标。
    pf_wrap_x=pfa_x+$signed(COORD_W'(pf_fragment_dx_q));
    if (!pf_stream_lookahead && c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
        c.kernel_w>1 && c.kernel_h>1 && c.dilation_w==1 && c.dilation_h==1 &&
        pf_kernel_advance_q>=32'(c.kernel_w) &&
        pf_kernel_advance_q<2*32'(c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(pfa_y)+1;
    end
    // 小通道的跨步窗口预测后续两个输出位置，字偏移决定预测距离。
    pf_window_ahead=!pf_stream_lookahead && c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
      (c.stride_h>1 || c.stride_w>1);
    pf_ahead_two=!pf_distance[0];
    pf_wrap_once=pfa_output_x==32'(last_output_col_q) ||
      (pf_ahead_two && pfa_output_x==32'(second_last_col_q));
    pf_wrap_twice=c.output_w==1 && pf_ahead_two;
    pf_window_x=pfa_x+$signed(COORD_W'(pf_window_dx_q));
    pf_window_y=pfa_y+$signed(COORD_W'(pf_window_dy_q));
    if(pf_window_ahead) begin pf_x=32'(pf_window_x);pf_y=32'(pf_window_y);end
    pf_coordinate_valid=pfa_x>=0 && pfa_y>=0 && pfa_x<$signed(COORD_W'(c.input_w)) &&
      pfa_y<$signed(COORD_W'(c.input_h)) &&
      (!pf_window_ahead || (pf_window_row_valid_q && pf_window_x>=0 && pf_window_y>=0));
    pf_channel=epoch_o_sum[4];
    // Two ways retain the active and following channel fragments when each
    // spatial pixel has a distinct set. Both fragments use physical tags.
    pf_next_fragment=fragment_image_fits && pfa_ref_index_valid && pfa_rows==1 &&
      pfa_cols==LINE_BYTES && !c.input_s16 &&
      ((32'(c.group_offset)+pfa_origin_channel)&(LINE_BYTES-1))==0 &&
      pfa_origin_channel+2*LINE_BYTES<=32'(c.group_c) &&
      (!pf_window_ahead || pf_distance==LINE_BYTES/4);
  end

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else begin
      case (prefetch_phase)
        0: if (cache_port_valid && cache_port_ready && c.prefetch_enable) begin
          prefetch_phase <= 1;
          // 预取上下文与实际接收地址同时保存，连续换行和换描述符时使用新坐标。
          pfa_x <= !REGISTER_CACHE_REQUEST && incoming_context ? incoming_ix :
              !REGISTER_CACHE_REQUEST && next_row_request ? next_row_ix : ix;
          pfa_y <= !REGISTER_CACHE_REQUEST ? request_y : iy;
          pfa_channel <= !REGISTER_CACHE_REQUEST && incoming_context ? incoming_ch :
              !REGISTER_CACHE_REQUEST && next_row_request ? ch0 :
              !REGISTER_CACHE_REQUEST && stream_next_request ? stream_channel_full : ch;
          pfa_origin_channel <= !REGISTER_CACHE_REQUEST && incoming_context ? incoming_ch : ch0;
          pfa_output_x <= !REGISTER_CACHE_REQUEST && incoming_next_position_fast && incoming_context ?
              {16'd0, window_next_x} : !REGISTER_CACHE_REQUEST &&
              (next_row_request || (incoming_context && incoming_next_tile_fast)) ?
              (row_wrap ? 32'd0 : ox+32'd1) : ox;
          pfa_output_y <= !REGISTER_CACHE_REQUEST ? request_output_y : oy;
          pfa_kernel_x <= !REGISTER_CACHE_REQUEST && incoming_context ? incoming_kx :
              !REGISTER_CACHE_REQUEST && next_row_request ? kx0 : kx;
          pfa_kernel_y <= !REGISTER_CACHE_REQUEST && incoming_context ? 16'(incoming_ky) :
              !REGISTER_CACHE_REQUEST && next_row_request ? ky0_q : ky_q;
          pfa_rows <= !REGISTER_CACHE_REQUEST && incoming_context ? 32'(tile_rows) : 32'(rows_q);
          pfa_cols <= !REGISTER_CACHE_REQUEST && incoming_context ?
              (tile_cols=='0 ? 32'(SIZE) : 32'(tile_cols)) : 32'(cols_q);
          pfa_ref_addr <= REGISTER_CACHE_REQUEST ? (request_pending ? request_addr_q : addr) : cache_req_addr;
          pfa_ref_index <= REGISTER_CACHE_REQUEST ? (request_pending ? request_index_q : current_req_index) : req_index;
          pfa_ref_epoch <= REGISTER_CACHE_REQUEST ? (request_pending ? request_epoch_q : current_req_epoch) : req_epoch;
          pfa_ref_index_valid <= request_pending ? request_index_valid_q : req_index_valid;
        end
        1: begin
          pf_y_delta_q <= pf_y_delta;
          pf_y_wrap_delta_q <= pf_y_wrap_delta;
          pf_distance_q <= pf_stream_lookahead ? 32'd4 :
              (c.windowed ? 1+(((pfa_channel-pfa_origin_channel)<<c.input_s16)>>2) : 32'd1);
          prefetch_phase <= 2;
        end
        2: begin
          pf_y_base_q <= pf_prepare_o_sum[0];
          pf_y_wrapped_q <= pf_prepare_o_sum[1];
          pf_kernel_advance_q <= pf_prepare_o_sum[2];
          // 固定提前四个缓存行的像素范围，最长限制为一行，便于逐行迭代。
          if (pf_stream_lookahead)
            pf_step_q <= (pf_step_base << 2) > {16'd0,c.input_w} ?
                {16'd0,c.input_w} : pf_step_base << 2;
          else
            pf_step_q <= pf_step_base * pf_distance_q;
          pf_fragment_dx_q <= tap_wrap_dx+$signed(33'(pf_distance_q))-33'sd1;
          if (c.output_w==1) pf_window_dx_q<=0;
          else if (pf_wrap_once) pf_window_dx_q<=pf_ahead_two ? row_pair_dx : row_wrap_dx;
          else pf_window_dx_q<=$signed(33'(c.stride_w)<<pf_ahead_two);
          pf_window_dy_q<=pf_wrap_twice ? (17'(c.stride_h)<<1) :
                            pf_wrap_once ? 17'(c.stride_h) : 17'd0;
          pf_window_row_valid_q<=pf_wrap_twice ?
              (c.output_h>1 && pfa_output_y<32'(second_last_row_q)) :
              (!pf_wrap_once || pfa_output_y<32'(retire_last_row_q));
          prefetch_phase <= 3;
        end
        3: begin
          pf0_x <= pf_x; pf0_y <= pf_y; pf0_channel <= pf_channel;
          pf0_epoch <= pfa_ref_epoch;
          pf0_ref_addr <= pfa_ref_addr; pf0_ref_index <= pfa_ref_index;
          pf0_ref_epoch <= pfa_ref_epoch; pf0_ref_retire <= retirement_result[1];
          pf0_ref_index_valid <= pfa_ref_index_valid; pf0_fragment <= pf_next_fragment;
          pf0_coordinate_valid <= pf_coordinate_valid;
          prefetch_phase <= 4;
        end
        4: begin
          pf1_pixel <= pf0_y * 32'(c.input_w) + pf0_x;
          pf1_channel <= pf0_channel; pf1_epoch <= pf0_epoch; pf1_retire <= retirement_result[1];
          pf1_ref_addr <= pf0_ref_addr; pf1_ref_index <= pf0_ref_index;
          pf1_ref_epoch <= pf0_ref_epoch; pf1_ref_retire <= pf0_ref_retire;
          pf1_ref_index_valid <= pf0_ref_index_valid; pf1_fragment <= pf0_fragment;
          pf1_coordinate_valid <= pf0_coordinate_valid && pf0_x<32'(c.input_w) && pf0_y<32'(c.input_h);
          prefetch_phase <= 5;
        end
        5: begin
          pf_channel_product<=pf1_pixel*32'(c.input_c);
          prefetch_phase<=6;
        end
        6: begin
          pf_addr<=pf_address_calc;
          prefetch_phase<=7;
        end
        7: begin
          pf_offer_valid <= pf1_fragment || (pf1_coordinate_valid &&
              (pf_addr>>$clog2(LINE_BYTES))!=(pf1_ref_addr>>$clog2(LINE_BYTES)));
          prefetch_phase<=8;
        end
        default: prefetch_phase <= 0;
      endcase
    end
  end

  always_comb begin
    pf_address_calc=c.input_base+((pf_channel_product+pf1_channel)<<c.input_s16);
    pf_index_valid=pf1_ref_index_valid; pf_index=pf1_pixel; pf_epoch=pf1_epoch;
    if (short_pixel_q)
      pf_index=pf1_pixel>>window_index_shift_q;
    if (!pf1_coordinate_valid && pf1_fragment) begin
      pf_address_calc=pf1_ref_addr;pf_index=pf1_ref_index;pf_epoch=pf1_ref_epoch;
    end
    pf_valid=prefetch_phase==8 && pf_offer_valid;
  end

  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。
  // 描述符准备和状态提交分开保存，候选算术在专用寄存器前完成。
  assign prepared_columns = tile_cols == '0 ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
  if (TILE_COUNT_W < 32) begin : g_prepared_active_columns
    localparam int p_high_width = 32 - TILE_COUNT_W;
    logic [TILE_COUNT_W-1:0] distance_low;
    logic [p_high_width-1:0] high_i_a, high_i_b, high_i_target;
    logic high_i_carry, high_o_equal;
    assign distance_low = reduction_len[TILE_COUNT_W-1:0] - tile_q0[TILE_COUNT_W-1:0];
    assign high_i_carry = reduction_len[TILE_COUNT_W-1:0] < tile_q0[TILE_COUNT_W-1:0];
    assign high_i_a = tile_q0[31:TILE_COUNT_W];
    assign high_i_b = '0;
    assign high_i_target = reduction_len[31:TILE_COUNT_W];
    add_equal #(.p_width(p_high_width)) u_distance_high (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_i_carry), .o_equal(high_o_equal)
    );
    assign prepared_active_columns = high_o_equal && distance_low < prepared_columns ?
      distance_low : prepared_columns;
  end else begin : g_prepared_active_columns_wide
    assign prepared_active_columns = reduction_len - tile_q0 < 32'(prepared_columns) ?
      TILE_COUNT_W'(reduction_len - tile_q0) : prepared_columns;
  end
  assign prepared_group_i_a = {1'b0, tile_q0};
  assign prepared_group_i_b = {17'd0, c.group_c};
  assign prepared_group_i_carry = 1'b0;
  parallel_prefix_add #(.p_width(33), .p_group_width(4), .p_preserve_groups(1'b1)) u_prepared_group (
    .i_a(prepared_group_i_a), .i_b(prepared_group_i_b), .i_carry(prepared_group_i_carry),
    .o_sum(prepared_next_group), .o_carry(unused_prepared_group_carry)
  );
  // 坐标基址与步长在准备阶段保存，完整坐标求和在提交寄存器前完成。
  always_comb begin
    prepared_coordinate_x = row_base_ix;
    prepared_coordinate_y = row_base_iy;
    prepared_coordinate_dx = '0;
    prepared_coordinate_dy = '0;
    prepared_coordinate_carry = '0;
    if (incoming_next_position_fast) begin
      prepared_coordinate_x = window_next_ix;
      prepared_coordinate_y = window_next_iy;
      if (incoming_position_previous_row) begin
        prepared_coordinate_dx = COORD_W'(c.dilation_w);
        prepared_coordinate_dy = ~COORD_W'(c.dilation_h);
        prepared_coordinate_carry[1] = 1'b1;
      end else if (incoming_position_forward_tap) begin
        prepared_coordinate_dx = COORD_W'(c.dilation_w);
      end else if (incoming_position_backward_tap) begin
        prepared_coordinate_dx = ~COORD_W'(c.dilation_w);
        prepared_coordinate_carry[0] = 1'b1;
      end
    end else if (incoming_next_tile_fast) begin
      prepared_coordinate_dx = row_wrap ? COORD_W'(row_wrap_dx) : COORD_W'(c.stride_w);
      prepared_coordinate_dy = row_wrap ? COORD_W'(c.stride_h) : '0;
    end else if (incoming_skip_tap) begin
      prepared_coordinate_dx = kx0_q != 16'd0 ? tap_pair_dx : COORD_W'(c.dilation_w) << 1;
      prepared_coordinate_dy = kx0_q != 16'd0 ? COORD_W'(c.dilation_h) : '0;
    end else if (!incoming_q_equal) begin
      prepared_coordinate_dx = incoming_tap_wrap ? COORD_W'(tap_wrap_dx) : COORD_W'(c.dilation_w);
      prepared_coordinate_dy = incoming_tap_wrap ? COORD_W'(c.dilation_h) : '0;
    end
  end
  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_coordinate
    logic [COORD_W-1:0] coordinate_i_a, coordinate_i_b;
    logic coordinate_i_carry;
    assign coordinate_i_a = axis == 0 ? prepared_tile_q.input_x : prepared_tile_q.input_y;
    assign coordinate_i_b = axis == 0 ? prepared_tile_q.coordinate_dx : prepared_tile_q.coordinate_dy;
    assign coordinate_i_carry = axis == 0 ? prepared_tile_q.coordinate_x_carry : prepared_tile_q.coordinate_y_carry;
    parallel_prefix_add #(.p_width(COORD_W), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(coordinate_i_a), .i_b(coordinate_i_b), .i_carry(coordinate_i_carry),
      .o_sum(committing_coordinate[axis]), .o_carry(unused_committing_coordinate_carry[axis])
    );
  end
  // 填充和字命中的候选值、选择条件分别保存，提交阶段只归并单比特结果。
  assign prepared_padding_value = {window_previous_padding, window_backward_padding,
    window_forward_padding, window_next_padding, next_row_padding, incoming_skip_padding,
    incoming_wrap_padding, incoming_step_padding, incoming_base_padding};
  always_comb begin
    prepared_padding_select = '0;
    prepared_word_select = '0;
    if (incoming_next_position_fast) begin
      if (incoming_position_same_tap) prepared_padding_select[5] = 1'b1;
      else if (incoming_position_previous_row) prepared_padding_select[8] = 1'b1;
      else if (incoming_position_forward_tap) prepared_padding_select[6] = 1'b1;
      else prepared_padding_select[7] = 1'b1;
      if (incoming_position_previous_row) prepared_word_select[9] = 1'b1;
      else if (incoming_position_forward_tap) prepared_word_select[7] = 1'b1;
      else if (incoming_position_backward_tap) prepared_word_select[8] = 1'b1;
      else prepared_word_select[6] = 1'b1;
    end else if (incoming_next_tile_fast) begin
      prepared_padding_select[4] = 1'b1;
      prepared_word_select[5] = 1'b1;
    end else if (incoming_skip_tap) begin
      prepared_padding_select[3] = 1'b1;
      if (kx0_q != 16'd0) prepared_word_select[4] = 1'b1;
      else prepared_word_select[3] = 1'b1;
    end else if (!incoming_q_equal) begin
      if (incoming_tap_wrap) begin
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
  end
  // 地址候选与选择条件并行形成，末端按独热结果归并两类地址。
  assign prepared_address_candidate[0] = {row_group_base, row_base_addr};
  assign prepared_address_candidate[1] = incoming_address_sum[0];
  assign prepared_address_candidate[2] = incoming_address_sum[1];
  assign prepared_address_candidate[3] = incoming_address_sum[2];
  assign prepared_address_candidate[4] = incoming_address_sum[3];
  assign prepared_address_candidate[5] = {next_row_group_base, next_row_addr};
  assign prepared_address_candidate[6] = {window_next_group_base, window_next_addr};
  assign prepared_address_candidate[7] = incoming_address_sum[4];
  assign prepared_address_candidate[8] = incoming_address_sum[5];
  assign prepared_address_candidate[9] = incoming_address_sum[6];
  always_comb begin
    prepared_address = '0;
    unique case (1'b1)
      prepared_word_select[0]: prepared_address = prepared_address_candidate[0];
      prepared_word_select[1]: prepared_address = prepared_address_candidate[1];
      prepared_word_select[2]: prepared_address = prepared_address_candidate[2];
      prepared_word_select[3]: prepared_address = prepared_address_candidate[3];
      prepared_word_select[4]: prepared_address = prepared_address_candidate[4];
      prepared_word_select[5]: prepared_address = prepared_address_candidate[5];
      prepared_word_select[6]: prepared_address = prepared_address_candidate[6];
      prepared_word_select[7]: prepared_address = prepared_address_candidate[7];
      prepared_word_select[8]: prepared_address = prepared_address_candidate[8];
      prepared_word_select[9]: prepared_address = prepared_address_candidate[9];
      default: ;
    endcase
  end
  for (genvar target = 0; target < 2; target++) begin : g_prepared_word_target
    logic [31-p_word_shift:0] target_address;
    assign target_address = target == 0 ? word_addr[31:p_word_shift] : addr[31:p_word_shift];
    assign prepared_word_match[0][target] = row_base_addr[31:p_word_shift] == target_address;
    assign prepared_word_match[1][target] = incoming_candidate_word_match[0][target];
    assign prepared_word_match[2][target] = incoming_candidate_word_match[1][target];
    assign prepared_word_match[3][target] = incoming_candidate_word_match[2][target];
    assign prepared_word_match[4][target] = incoming_candidate_word_match[3][target];
    assign prepared_word_match[5][target] = next_row_word_match[target];
    assign prepared_word_match[6][target] = window_next_addr[31:p_word_shift] == target_address;
    assign prepared_word_match[7][target] = incoming_candidate_word_match[4][target];
    assign prepared_word_match[8][target] = incoming_candidate_word_match[5][target];
    assign prepared_word_match[9][target] = incoming_candidate_word_match[6][target];
  end
  for (genvar candidate = 0; candidate < 10; candidate++) begin : g_prepared_word_value
    assign prepared_word_value[candidate] = finishing_tile && state[$clog2(WAIT_WORD)] ?
      prepared_word_match[candidate][1] : word_valid && word_addr[p_word_shift-1:0] == '0 &&
      prepared_word_match[candidate][0];
  end
  always_comb begin
    preparing_tile = '0;
    preparing_tile.coordinate_dx = prepared_coordinate_dx;
    preparing_tile.coordinate_dy = prepared_coordinate_dy;
    preparing_tile.coordinate_x_carry = prepared_coordinate_carry[0];
    preparing_tile.coordinate_y_carry = prepared_coordinate_carry[1];
    preparing_tile.padding_select = prepared_padding_select;
    preparing_tile.padding_value = prepared_padding_value;
    preparing_tile.word_select = prepared_word_select;
    preparing_tile.word_value = prepared_word_value;
    preparing_tile.invalid = !channel_descriptor_valid;
    preparing_tile.fast = incoming_fast;
    preparing_tile.padding = incoming_padding;
    preparing_tile.word_hit = incoming_word_hit;
    preparing_tile.position = tile_p0;
    preparing_tile.reduction = tile_q0;
    preparing_tile.group_index = tile_group;
    preparing_tile.rows = TILE_COUNT_W'(tile_rows);
    preparing_tile.columns = prepared_columns;
    preparing_tile.active_columns = prepared_active_columns;
    preparing_tile.slot = tile_slot;
    preparing_tile.narrow_output = tile_narrow;
    preparing_tile.next_group = prepared_next_group;
    preparing_tile.geometry = pred_enabled && (CACHE_POLICY!=3 || !c.windowed) &&
      (tile_cols==0 || 32'(tile_cols)==SIZE) && tile_p0[3:0]==0 && tile_q0[3:0]==0 && tile_group<groups_q;
    preparing_tile.tap = incoming_tap;
    preparing_tile.channel = incoming_ch;
    preparing_tile.kernel_x = incoming_kx;
    preparing_tile.kernel_y = incoming_ky;
    preparing_tile.kernel_last = incoming_kx_last;
    preparing_tile.input_x = REGISTER_DESCRIPTOR ? prepared_coordinate_x : incoming_ix;
    preparing_tile.input_y = REGISTER_DESCRIPTOR ? prepared_coordinate_y : incoming_iy;
    preparing_tile.pixel = incoming_pixel;
    preparing_tile.address = REGISTER_DESCRIPTOR ? prepared_address[0] : incoming_addr;
    preparing_tile.group_address = REGISTER_DESCRIPTOR ? prepared_address[1] : incoming_group_base;
    preparing_tile.channel_range = incoming_next_position_fast ? window_next_channel_range : group_range_next[1];
    preparing_tile.output_position_update = incoming_next_position_fast || incoming_next_tile_fast;
    preparing_tile.output_x = incoming_next_position_fast ? window_next_x : row_wrap ? 16'd0 : ox_q + 16'd1;
    preparing_tile.output_y = incoming_next_position_fast ? window_next_y : row_wrap ? oy_q + 16'd1 : oy_q;
    preparing_tile.output_wrap = incoming_next_position_fast ? window_next_last_col :
      row_wrap ? last_output_col_q == 16'd0 : row_next_o_equal;
  end
  assign tile_capture = tile_valid && tile_ready;
  // 准备项可以在当前末拍提交，并在同一边沿接收后续描述符。
  assign tile_commit = REGISTER_DESCRIPTOR ?
    (tile_prepared_valid && !error && (state[$clog2(IDLE)] || finishing_tile)) : tile_capture;
  // 当前末拍与准备项的数据字相同，可直接使用本周期返回的数据。
  assign committing_saved_word_hit = |(prepared_tile_q.word_select & prepared_tile_q.word_value);
  assign prepared_live_word_match = prepared_tile_q.address[31:p_word_shift] == addr[31:p_word_shift];
  assign committing_live_word_hit = state[$clog2(WAIT_WORD)] && finishing_tile && prepared_live_word_match;
  always_comb begin
    committing_tile = REGISTER_DESCRIPTOR ? prepared_tile_q : preparing_tile;
    if (REGISTER_DESCRIPTOR) begin
      committing_tile.input_x = $signed(committing_coordinate[0]);
      committing_tile.input_y = $signed(committing_coordinate[1]);
      committing_tile.padding = |(prepared_tile_q.padding_select & prepared_tile_q.padding_value);
      committing_tile.word_hit = committing_saved_word_hit || committing_live_word_hit;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) tile_prepared_valid <= 1'b0;
    else if ((cfg_valid && cfg_ready) || error) tile_prepared_valid <= 1'b0;
    else if (REGISTER_DESCRIPTOR && tile_capture) tile_prepared_valid <= 1'b1;
    else if (tile_commit) tile_prepared_valid <= 1'b0;
  end
  always_ff @(posedge clk) begin
    if (tile_capture) begin
      prepared_tile_q <= preparing_tile;
      // 命中数据随准备项保存，后续窗口更新缓存字不会改变该描述符的内容。
      prepared_word_data <= finishing_tile && state[$clog2(WAIT_WORD)] ? cache_rsp_data : word_buf;
    end
  end

  assign channel_descriptor_valid = tile_rows != RW'(0) && 32'(tile_rows) <= SIZE &&
    32'(tile_cols) <= SIZE && tile_q_before_end && tile_rows_in_range;
  assign channel_accept_i_flags = {1'b1, incoming_fast, channel_descriptor_valid,
                                  tile_ready_context, !cfg_valid, tile_valid};
  assign channel_accept_fire = REGISTER_DESCRIPTOR ?
    tile_commit && !committing_tile.invalid && committing_tile.fast : &channel_accept_i_flags;
  always_comb begin
    channel_update = ch_q;
    case (1'b1)
      state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: begin
        if (!(state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) && wr_valid && wr_ready) begin
          if (chunk_reaches_end) begin
            if (!row_last_q) begin
              channel_update = 16'(ch0);
            end
          end else if (col_idx < active_cols_q && TILE_COUNT_W'(chunk_count) < active_remaining) begin
            if (group_end_o_equal) begin
              channel_update = 16'd0;
            end else begin
              channel_update = next_channel;
            end
          end
        end
      end
      state[$clog2(Q_DECODE)]: begin
        if (q0 == 32'd0) begin
          channel_update = 16'd0;
        end else if (group_shape_o_valid) begin
          channel_update = 16'(q0 & (32'(c.group_c) - 32'd1));
        end else if (c.group_c == 16'd3 && q0 < 32'd27) begin
          channel_update = current_q_remainder;
        end
      end
      state[$clog2(Q_WAIT)]: begin
        if (decode_index == q0) begin
          channel_update = 16'(decode_inner);
        end
      end
      default: ;
    endcase
  end
  // 行切换、组切换和通道递增先选择范围，写入握手只控制最终保存。
  (* keep = 1 *) logic [p_saved_group_lanes:0] group_range_stream_value;
  assign group_range_stream_value = chunk_reaches_end ? group_range_next[1] :
    group_end_o_equal ? group_range_next[0] : group_range_next[5];

  // 流式范围的保存资格与三种候选值并行计算，返回有效只控制寄存器写入。
  logic range_stream_allowed, range_context_write, range_decode_write;
  (* keep = 1 *) logic [p_saved_group_lanes:0] range_context_value, range_decode_value;
  always_comb begin
    range_stream_allowed = 1'b0;
    case (1'b1)
      state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: begin
        if (state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) begin
        end else if (wr_ready) begin
          if (chunk_reaches_end) begin
            if (row_last_q) begin
            end else range_stream_allowed = 1'b1;
          end else if (past_active_q || TILE_COUNT_W'(chunk_count) >= active_remaining) begin
          end else range_stream_allowed = 1'b1;
        end
      end
      default: ;
    endcase
    range_context_write = 1'b0;
    range_context_value = group_range_stream_value;
    if (cfg_valid && cfg_ready) begin
      range_context_write = 1'b1;
      range_context_value = group_range_cfg;
    end else if (tile_commit) begin
      range_context_value = committing_tile.channel_range;
      if (committing_tile.invalid) begin
      end else if (committing_tile.fast) range_context_write = 1'b1;
    end else if (wr_valid && range_stream_allowed) range_context_write = 1'b1;
  end
  // 译码选择保持状态优先次序，其数据准备与配置及输出握手独立。
  always_comb begin
    range_decode_write = 1'b0;
    range_decode_value = group_range_next[4];
    case (1'b1)
      state[$clog2(P_DECODE)], state[$clog2(P_START)], state[$clog2(P_WAIT)]: ;
      state[$clog2(Q_DECODE)]: begin
        if (q0 == 32'd0) begin
          range_decode_write = 1'b1;
          range_decode_value = group_range_next[0];
        end else if (group_shape_o_valid) begin
          range_decode_write = 1'b1;
          range_decode_value = group_range_next[2];
        end else if (c.group_c == 16'd3 && q0 < 32'd27) begin
          range_decode_write = 1'b1;
          range_decode_value = group_range_next[3];
        end
      end
      state[$clog2(Q_START)]: ;
      state[$clog2(Q_WAIT)]: begin
        if (decode_index == q0) range_decode_write = 1'b1;
      end
      default: ;
    endcase
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) group_range_q <= '0;
    else if (range_decode_write) group_range_q <= range_decode_value;
    else if (range_context_write) group_range_q <= range_context_value;
  end

  // 当前通道和新描述符并行准备，接收事件只选择最终数据。
  assign channel_value = channel_accept_fire ? 16'(committing_tile.channel) : channel_update;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      ch_q <= 16'd0;
    end else begin
      ch_q <= channel_value;
    end
  end

  // 保存前端配置、描述符和坐标状态。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      state<=IDLE; c<='0; configured<=0; error<=0; tile_done<=0; tile_error<=0;
      fragment_image_fits<=0;
      reduction_len<=0; position_count<=0; tensor_bytes<=0;
      position_high_minus_one_q <= '1;
      next_group_q <= 33'd0;
      p0<=0; q0<=0; tap0<=0; row_idx<=0; col_idx<=0; rows_q<=0; cols_q<=TILE_COUNT_W'(SIZE);active_cols_q<=0;
      row_last_q <= 1'b0;
      row_wrap_q <= 1'b0;
      tap_wrap_q <= 1'b0;
      incoming_tap_wrap_q <= 1'b0;
      col_remaining <= TILE_COUNT_W'(SIZE);
      active_remaining <= '0;
      past_active_q <= 1'b1;
      narrow_output <= 1'b0;
      ox_q <= 16'(0); oy_q <= 16'(0); ky_q <= 16'(0); kx_q <= 16'(0); ky0_q <= 16'(0); kx0_q <= 16'(0); ch0_q <= 16'(0);

      tap_group_base<=0;row_group_base<=0;
      q_current<=0; ix <= COORD_W'(0); iy <= COORD_W'(0); pixel_index <= 32'(0); pad_q<=0; addr<=0;
      word_buf<=0; word_addr<=0; word_valid<=0; addr_word_hit_q<=0; slot_q<=0;
      group_q<=0;groups_q<=0;geometry_tile<=0;line_hint_valid<=0;line_hint_rank<=32'hffff_ffff;
      p_cache_valid<=0;last_p_valid<=0;last_p<=0;last_p_limit<=0;last_y<=0;last_x<=0;
      address_step_phase<=0;row_wrap_dx <= 33'(0);tap_wrap_dx <= 33'(0);row_pair_dx<=0;
      row_y_pixels <= 33'(0);tap_y_pixels <= 33'(0);row_wrap_pixels <= 33'(0);tap_wrap_pixels <= 33'(0);
      row_step_bytes<=0;tap_step_bytes<=0;row_wrap_bytes<=0;tap_wrap_bytes<=0;group_bytes<=0;
      row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
      row_base_ix <= COORD_W'(0);row_base_iy <= COORD_W'(0);row_base_pixel <= 32'(0);row_base_addr<=0;
      for (int t=0;t<4;t++) begin p_cache_key[t]<=0;p_cache_y[t]<=0;p_cache_x[t]<=0;end
    end else begin
      tile_done<=finishing_tile; tile_error<=0;
      if (state[$clog2(WAIT_WORD)] && wr_valid && wr_ready) begin
        word_buf<=cache_rsp_data;word_addr<={addr[31:p_word_shift],{p_word_shift{1'b0}}};word_valid<=1;addr_word_hit_q<=1;
      end
      if (address_step_phase==2) begin
        row_pair_dx<=row_wrap_dx+$signed(33'(c.stride_w));
        row_wrap_pixels <= 33'(row_y_pixels+$signed(COORD_W'(row_wrap_dx)));
        tap_wrap_pixels <= 33'(tap_y_pixels+$signed(COORD_W'(tap_wrap_dx)));
        address_step_phase<=1;
      end else if (address_step_phase==1) begin
        row_wrap_bytes<=32'(($unsigned(row_wrap_pixels)*COORD_W'(c.input_c))<<c.input_s16);
        tap_wrap_bytes<=32'(($unsigned(tap_wrap_pixels)*COORD_W'(c.input_c))<<c.input_s16);
        address_step_phase<=0;
      end
      if (cfg_prepare_phase==2) begin
        configured<=cfg_ok;error<=!cfg_ok;
        reduction_len<=32'(cfg_red);position_count<=cfg_positions;tensor_bytes<=32'(cfg_input_bytes);
        // 配置边沿同时保存位置上限及其高位减一值，供低位进位时比较。
        position_high_minus_one_q <= cfg_positions[31:p_row_low_w] - p_row_high_w'(1);
        fragment_image_fits<=CACHE_WAYS>=2 &&
          cfg_input_bytes<=((64'(c.input_c)<<c.input_s16)<<$clog2(CACHE_SETS));
      end
      if (pred_done) begin line_hint_valid<=1;line_hint_rank<=pred_rank;end
      if (pred_start) line_hint_valid<=0;
      if (cfg_valid && cfg_ready) begin
        row_wrap_q <= cfg.output_w != 16'd0 && ox_q == cfg_last_output_col;
        tap_wrap_q <= cfg.kernel_w != 16'd0 && kx_q == cfg_last_kernel_col;
        incoming_tap_wrap_q <= cfg.kernel_w != 16'd0 && kx0_q == cfg_last_kernel_col;
        c<=cfg; configured<=0; error<=!cfg_basic_valid;

        next_group_q <= {1'b0, q0} + 33'(cfg.group_c);
        word_valid<=0; addr_word_hit_q<=0; reduction_len<=0;
        fragment_image_fits<=0;
        position_count<=0; tensor_bytes<=0;
        position_high_minus_one_q <= '1;
        groups_q<=cfg_sched_groups;geometry_tile<=0;line_hint_valid<=0;
        p_cache_valid<=0;last_p_valid<=0;
        address_step_phase<=2;row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
        row_wrap_dx <= 33'(-$signed((64'(cfg.output_w)-1)*64'(cfg.stride_w)));
        tap_wrap_dx <= 33'(-$signed((64'(cfg.kernel_w)-1)*64'(cfg.dilation_w)));
        row_y_pixels <= 33'($signed(64'(cfg.stride_h)*64'(cfg.input_w)));
        tap_y_pixels <= 33'($signed(64'(cfg.dilation_h)*64'(cfg.input_w)));
        row_step_bytes<=32'((64'(cfg.stride_w)*64'(cfg.input_c))<<cfg.input_s16);
        tap_step_bytes<=32'((64'(cfg.dilation_w)*64'(cfg.input_c))<<cfg.input_s16);
        group_bytes<=32'(cfg.group_c)<<cfg.input_s16;
      end else if (tile_commit) begin
        if (committing_tile.invalid) begin
          tile_error<=1; error<=1; state<=IDLE;
        end else begin
          p0<=committing_tile.position; q0<=committing_tile.reduction;
          q_current<={1'b0,committing_tile.reduction};
          next_group_q <= committing_tile.next_group;
          row_last_q <= committing_tile.rows == TILE_COUNT_W'(1);
          rows_q<=committing_tile.rows; cols_q<=committing_tile.columns;
          col_remaining <= committing_tile.columns;
          active_cols_q <= committing_tile.active_columns;
          active_remaining <= committing_tile.active_columns;
          past_active_q <= 1'b0;
          row_idx<=0; col_idx<=0; slot_q<=committing_tile.slot;
          narrow_output <= committing_tile.narrow_output;
          group_q<=committing_tile.group_index;
          row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
          geometry_tile<=committing_tile.geometry;
          if (committing_tile.fast) begin
            tap0<=committing_tile.tap; ch0_q<=16'(committing_tile.channel);

            if (committing_tile.output_position_update) begin
              ox_q<=committing_tile.output_x; oy_q<=committing_tile.output_y;
              row_wrap_q<=committing_tile.output_wrap;
            end
            ky_q<=16'(committing_tile.kernel_y); ky0_q<=16'(committing_tile.kernel_y);
            kx_q<=16'(committing_tile.kernel_x); kx0_q<=16'(committing_tile.kernel_x);
            tap_wrap_q<=kernel_width_valid_q && committing_tile.kernel_last;
            incoming_tap_wrap_q<=kernel_width_valid_q && committing_tile.kernel_last;
            ix<=committing_tile.input_x; iy<=committing_tile.input_y;
            pixel_index<=committing_tile.pixel; addr<=committing_tile.address; addr_word_hit_q<=committing_tile.word_hit;
            if (REGISTER_DESCRIPTOR && committing_saved_word_hit) begin
              word_buf <= prepared_word_data;
              word_addr <= {committing_tile.address[31:p_word_shift],{p_word_shift{1'b0}}};
              word_valid <= 1'b1;
            end
            pad_q<=committing_tile.padding;
            tap_group_base<=committing_tile.group_address; row_group_base<=committing_tile.group_address;
            row_base_valid<=1;coordinate_address_valid<=1;row_coordinate_valid<=1;current_coordinate_valid<=1;
            row_base_ix<=committing_tile.input_x; row_base_iy<=committing_tile.input_y;
            row_base_pixel<=committing_tile.pixel; row_base_addr<=committing_tile.address;
            if (committing_tile.padding) state<=ZERO_STREAM;
            else if (committing_tile.word_hit) state<=STREAM;
            else if (REGISTER_CACHE_REQUEST || REGISTER_DESCRIPTOR) state<=FETCH;
            else state<=cache_req_ready ? WAIT_WORD : FETCH;
          end else state<=P_DECODE;
        end
      end else case (1'b1)
        state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: begin
          if (state[$clog2(WAIT_WORD)] && cache_rsp_valid && cache_rsp_error) begin
            error<=1;tile_error<=1;state<=IDLE;
          end else if (wr_valid && wr_ready) begin
          if (chunk_reaches_end) begin
            if (row_last_q) begin tile_done<=1; state<=IDLE; end
            else begin
              row_idx<=next_row_idx; row_last_q<=next_row_last; col_idx<=0; q_current<={1'b0,q0};
               col_remaining <= cols_q;
               active_remaining <= active_cols_q;
               past_active_q <= 1'b0;
              ky_q <= 16'(ky0); kx_q <= 16'(kx0); tap_wrap_q <= kernel_width_valid_q && (16'(kx0) == last_kernel_col_q);

              if (row_wrap) begin ox_q <= 16'(0); row_wrap_q <= c.output_w != 16'd0 && (16'(0) == last_output_col_q); oy_q <= 16'(oy+1); end
              else begin
                ox_q <= 16'(ox+1);
                row_wrap_q <= c.output_w != 16'd0 && row_next_o_equal;
              end
              if (row_base_valid && !geometry_tile) begin
                ix <= COORD_W'(next_row_ix);iy <= COORD_W'(next_row_iy);pixel_index <= 32'(next_row_pixel);
                addr<=next_row_addr; addr_word_hit_q<=next_row_word_hit;pad_q<=next_row_padding;coordinate_address_valid<=1;
                tap_group_base<=next_row_group_base;row_group_base<=next_row_group_base;
                row_base_ix <= COORD_W'(next_row_ix);row_base_iy <= COORD_W'(next_row_iy);
                row_base_pixel <= 32'(next_row_pixel);row_base_addr<=next_row_addr;
                if (next_row_padding) state<=ZERO_STREAM;
                else if (next_row_word_hit) state<=STREAM;
                else state<=next_row_request && cache_req_ready ? WAIT_WORD : FETCH;
              end else if (row_coordinate_valid) begin
                ix<=next_row_ix;iy<=next_row_iy;
                row_base_ix<=next_row_ix;row_base_iy<=next_row_iy;
                row_base_valid<=0;coordinate_address_valid<=0;state<=ADDRESS;
              end else begin row_base_valid<=0;state<=COORD;end
            end
          end else begin
            col_idx<=col_idx+TILE_COUNT_W'(chunk_count); q_current<=next_q_current;
            // 填充列同样推进计数，保留原有定宽减法的回绕结果。
            col_remaining <= col_remaining - TILE_COUNT_W'(chunk_count);
             active_remaining <= active_remaining - TILE_COUNT_W'(chunk_count);
             // 仅在写入握手时推进；到达有效尾部后保持，直到下一行或描述符。
             past_active_q <= past_active_q || TILE_COUNT_W'(chunk_count)>=active_remaining;
             if (past_active_q || TILE_COUNT_W'(chunk_count)>=active_remaining) state<=ZERO_STREAM;
            else if (group_end_o_equal) begin


              if (coordinate_address_valid) begin
                if (tap_wrap) begin kx_q <= 16'(0);
                tap_wrap_q <= kernel_width_valid_q && (16'(0) == last_kernel_col_q);
                ky_q <= 16'(ky+1);
                end
                else begin
                  kx_q <= 16'(kx+1);
                  tap_wrap_q <= kernel_width_valid_q && tap_next_o_equal;
                end
                ix <= COORD_W'(next_tap_ix);iy <= COORD_W'(next_tap_iy);pixel_index <= 32'(next_tap_pixel);
                addr<=next_tap_addr; addr_word_hit_q<=next_tap_saved_hit;pad_q<=next_tap_padding;tap_group_base<=next_tap_addr;
                if (next_tap_padding) state<=ZERO_STREAM;
                else if (next_word_o_equal && !pad_q) state<=STREAM;
                else state<=FETCH;
              end else if (current_coordinate_valid) begin
                if (tap_wrap) begin kx_q<=0; tap_wrap_q <= kernel_width_valid_q && (16'(0) == last_kernel_col_q);ky_q<=16'(ky+1);end
                else begin
                  kx_q <= 16'(kx+1);
                  tap_wrap_q <= kernel_width_valid_q && tap_next_o_equal;
                end
                ix<=next_tap_ix;iy<=next_tap_iy;
                coordinate_address_valid<=0;state<=ADDRESS;
              end else if (tap_wrap) begin kx_q <= 16'(0);
              tap_wrap_q <= kernel_width_valid_q && (16'(0) == last_kernel_col_q);
              ky_q <= 16'(ky+1);
              state<=COORD;
              end
              else begin
                kx_q <= 16'(kx+1); tap_wrap_q <= kernel_width_valid_q && tap_next_o_equal;
                if (!pad_q && c.group_c==c.input_c && c.group_offset==0 && c.dilation_w==1 &&
                    ix_step_below_limit) begin
                  ix <= $signed(ix_increment);pixel_index <= 32'(pixel_index+1);addr<=next_byte_addr; addr_word_hit_q<=next_byte_saved_hit;
                  if (!word_boundary) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
                end else state<=COORD;
              end
            end else begin


              if (pad_q) begin addr<=next_byte_addr; addr_word_hit_q<=next_byte_saved_hit;state<=ZERO_STREAM;end
              else begin
                addr<=next_byte_addr; addr_word_hit_q<=next_byte_saved_hit;
                if (!word_boundary) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
              end
            end
          end
        end
        end
        default: ;
      endcase
      case (1'b1)
        state[$clog2(P_DECODE)]: if (p_fast_valid) begin
          oy_q <= 16'(p_fast_y);ox_q <= 16'(p_fast_x); row_wrap_q <= p_fast_wrap;state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_y<=16'(p_fast_y);last_x<=16'(p_fast_x);
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=16'(p_fast_y);p_cache_x[p_cache_select]<=16'(p_fast_x);
        end else state<=P_START;
        state[$clog2(P_START)]: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=P_WAIT;end
        state[$clog2(P_WAIT)]: if (decode_index==p0) begin
          oy_q <= 16'(decode_outer);
          ox_q <= 16'(decode_inner);
          row_wrap_q <= c.output_w != 16'd0 && (16'(decode_inner) == last_output_col_q);
          state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_y<=16'(decode_outer);last_x<=16'(decode_inner);
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=16'(decode_outer);p_cache_x[p_cache_select]<=16'(decode_inner);
        end else begin
          decode_index<=decode_index+1;
          if (decode_end_o_equal[0]) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        state[$clog2(Q_DECODE)]: begin
          if (q0==0) begin
            tap0<=0;ch0_q <= 16'(0);state<=K_DECODE;

          end
          else if (group_shape_o_valid) begin
            tap0<=q0>>power_shift(32'(c.group_c));
            ch0_q <= 16'(q0&(32'(c.group_c)-1));state<=K_DECODE;

          end else if (c.group_c==3 && q0<27) begin
            tap0<=32'(current_q_div3);

            ch0_q <= current_q_remainder;

            state<=K_DECODE;
          end else state<=Q_START;
        end
        state[$clog2(Q_START)]: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=Q_WAIT;end
        state[$clog2(Q_WAIT)]: if (decode_index==q0) begin
          tap0<=decode_outer; ch0_q <= 16'(decode_inner); state<=K_DECODE;

        end
        else begin
          decode_index<=decode_index+1;
          if (decode_end_o_equal[1]) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        state[$clog2(K_DECODE)]: begin
          if (kernel_shape_o_valid) begin
            ky_q <= 16'(tap0>>power_shift(32'(c.kernel_w)));ky0_q <= 16'(tap0>>power_shift(32'(c.kernel_w)));
            kx_q <= 16'(tap0&(32'(c.kernel_w)-1));
            tap_wrap_q <= kernel_width_valid_q && (16'(tap0&(32'(c.kernel_w)-1)) == last_kernel_col_q);
            kx0_q <= 16'(tap0&(32'(c.kernel_w)-1));
            incoming_tap_wrap_q <= kernel_width_valid_q && (16'(tap0&(32'(c.kernel_w)-1)) == last_kernel_col_q);
            state<=COORD;
          end else if (c.kernel_w==3 && tap0<9) begin
            if (tap0<3) begin
              ky_q <= 16'(0);
              ky0_q <= 16'(0);
              kx_q <= 16'(tap0);
              tap_wrap_q <= kernel_width_valid_q && (16'(tap0) == last_kernel_col_q);
              kx0_q <= 16'(tap0);
              incoming_tap_wrap_q <= kernel_width_valid_q && (16'(tap0) == last_kernel_col_q);
            end else if (tap0<6) begin
              ky_q <= 16'(1);
              ky0_q <= 16'(1);
              kx_q <= 16'(tap0-3);
              tap_wrap_q <= kernel_width_valid_q && (16'(tap0-3) == last_kernel_col_q);
              kx0_q <= 16'(tap0-3);
              incoming_tap_wrap_q <= kernel_width_valid_q && (16'(tap0-3) == last_kernel_col_q);
            end else begin
              ky_q <= 16'(2);
              ky0_q <= 16'(2);
              kx_q <= 16'(tap0-6);
              tap_wrap_q <= kernel_width_valid_q && (16'(tap0-6) == last_kernel_col_q);
              kx0_q <= 16'(tap0-6);
              incoming_tap_wrap_q <= kernel_width_valid_q && (16'(tap0-6) == last_kernel_col_q);
            end
            state<=COORD;
          end else state<=K_START;
        end
        state[$clog2(K_START)]: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=K_WAIT;end
        state[$clog2(K_WAIT)]: if (decode_index==tap0) begin
          ky_q <= 16'(decode_outer);
          ky0_q <= 16'(decode_outer);
          kx_q <= 16'(decode_inner);
          tap_wrap_q <= kernel_width_valid_q && (16'(decode_inner) == last_kernel_col_q);
          kx0_q <= 16'(decode_inner);
          incoming_tap_wrap_q <= kernel_width_valid_q && (16'(decode_inner) == last_kernel_col_q);
          state<=COORD;
        end else begin
          decode_index<=decode_index+1;
          if (decode_end_o_equal[2]) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        state[$clog2(COORD)]: begin
          coordinate_address_valid<=0;current_coordinate_valid<=0;
          coord_out_x<=32'(ox_q)*32'(c.stride_w);
          coord_out_y<=32'(oy_q)*32'(c.stride_h);
          coord_kernel_x<=32'(kx_q)*32'(c.dilation_w);
          coord_kernel_y<=32'(ky_q)*32'(c.dilation_h);
          state<=COORD_SUM;
        end
        state[$clog2(COORD_SUM)]: begin
          coord_sum_x<={1'b0,coord_out_x}+{1'b0,coord_kernel_x};
          coord_sum_y<={1'b0,coord_out_y}+{1'b0,coord_kernel_y};
          state<=COORD_PAD;
        end
        state[$clog2(COORD_PAD)]: begin
          current_coordinate_valid<=1;
          ix<=$signed(COORD_W'(coord_sum_x))-$signed(COORD_W'(c.pad_left));
          iy<=$signed(COORD_W'(coord_sum_y))-$signed(COORD_W'(c.pad_top));
          state<=ADDRESS;
        end
        state[$clog2(ADDRESS)]: begin
          if (col_idx==0) begin
            row_coordinate_valid<=1;row_base_ix<=ix;row_base_iy<=iy;
          end
          if (q_current >= {1'b0,reduction_len} || ix<0 || iy<0 ||
              ix >= $signed(COORD_W'(c.input_w)) || iy >= $signed(COORD_W'(c.input_h))) begin
            pad_q<=1; state<=ZERO_STREAM;
          end else if (!geometry_tile || col_idx!=0 || (!pred_busy && !cache_hint_pending)) begin
            pixel_product <= 32'(iy[15:0]) * 32'(c.input_w);
            pad_q<=0; state<=ADDRESS_PIXEL;
          end
        end
        state[$clog2(ADDRESS_PIXEL)]: begin
          pixel_index<=pixel_product+32'(ix);
          state<=ADDRESS_PRODUCT;
        end
        state[$clog2(ADDRESS_PRODUCT)]: begin
          channel_product<=pixel_index*32'(c.input_c);
          state<=ADDRESS_BASE;
        end
        state[$clog2(ADDRESS_BASE)]: begin
          group_base_addr<=c.input_base+((channel_product+32'(c.group_offset))<<c.input_s16);
          state<=ADDRESS_CHANNEL;
        end
        state[$clog2(ADDRESS_CHANNEL)]: begin
          addr<=channel_addr; addr_word_hit_q<=channel_saved_hit;
          tap_group_base<=group_base_addr;
          coordinate_address_valid<=1;
          if (col_idx==0) begin
            row_base_valid<=1;row_base_ix<=ix;row_base_iy<=iy;row_base_pixel<=pixel_index;
            row_base_addr<=channel_addr;
            row_group_base<=group_base_addr;
          end
          state<=FETCH;
        end
        state[$clog2(FETCH)]: begin
          if (current_word_hit) state<=STREAM;
          else if (cache_req_ready) state<=WAIT_WORD;
        end
        state[$clog2(IDLE)], state[$clog2(WAIT_WORD)], state[$clog2(STREAM)], state[$clog2(ZERO_STREAM)]: ;
        default: begin state<=IDLE; configured<=0; error<=1; end
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
endmodule

`default_nettype wire
