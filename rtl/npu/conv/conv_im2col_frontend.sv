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
  input wire logic clk, // 前端和缓存接口的工作时钟。
  input wire logic rst_n, // 低有效异步复位。
  input wire logic cfg_valid, // 卷积配置有效。
  output logic cfg_ready, // 前端能够接收卷积配置。
  input wire conv_im2col_pkg::conv_cfg_t cfg, // 卷积几何、格式和地址配置。
  // IA 调度上下文中的组数为零时关闭几何预测，支持任意描述符顺序。
  input wire logic [31:0] cfg_sched_r = 32'd0, // 调度上下文中的归约长度。
  input wire logic [31:0] cfg_sched_groups = 32'd0, // 调度上下文中的通道组数。
  input wire logic tile_valid, // 输入分块描述符有效。
  output logic tile_ready, // 前端能够接收分块描述符。
  input wire logic [31:0] tile_p0, // 分块首个输出位置索引。
  input wire logic [31:0] tile_q0, // 分块首个归约位置索引。
  input wire logic [RW-1:0] tile_rows, // 分块包含的输出行数。
  input wire logic [RW-1:0] tile_cols = '0, // 零值选择完整的 SIZE 列。
  input wire logic [SLOT_W-1:0] tile_slot, // 分块写入的目标存储槽。
  input wire logic [31:0] tile_group = 32'd0, // 分块所属的通道组索引。
  input wire logic tile_narrow = 1'b0, // 使用窄通道输出格式。
  output logic wr_valid, // 当前校正数据输出有效。
  input wire logic wr_ready, // 目标存储能够接收当前输出。
  output logic [SLOT_W-1:0] wr_slot, // 当前输出的目标存储槽。
  output logic [CW-1:0] wr_row, // 当前输出的分块行索引。
  output logic [CW-1:0] wr_col, // 当前输出的首个列索引。
  output logic signed [15:0] wr_data [LANES], // 各写入通道的有符号校正数据。
  output logic [LANES-1:0] wr_mask, // 各写入通道的有效位。
  output logic tile_done, // 分块输出完成脉冲。
  output logic tile_error, // 当前分块错误脉冲。
  output logic error, // 配置或运行过程中保存的累计错误。
  output logic busy, // 前端仍有配置或运行任务。
  output logic wr_last, // 当前输出为分块最后一次传输。
  output logic arvalid, // AXI 读地址请求有效。
  input wire logic arready, // AXI 读地址请求可被接收。
  output logic [31:0] araddr, // AXI 读突发的起始字节地址。
  output logic [7:0] arlen, // AXI 读突发拍数减一。
  output logic [2:0] arsize, // AXI 每拍传输的字节数编码。
  output logic [1:0] arburst, // AXI 读突发地址递增类型。
  input wire logic rvalid, // AXI 读返回数据有效。
  output logic rready, // 前端能够接收 AXI 读返回数据。
  input wire logic [BUS_WIDTH-1:0] rdata, // AXI 读返回数据。
  input wire logic [1:0] rresp, // AXI 读返回状态。
  input wire logic rlast // AXI 读突发的最后一拍。
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
  st_t selected_state;
  logic descriptor_commit_eligible;
  logic stream_response_error;
  logic stream_output_accept;
  logic stream_operation_accept;
  logic stream_transfer_accept;
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
  logic [31:0] pixel_product, address_pixel_sum;
  logic [31:0] channel_product;
  logic [31:0] group_base_addr;
  logic [31:0] channel_addr;
  logic [31:0] tap_group_base;
  logic [31:0] row_group_base;
  logic descriptor_payload_context;
  logic [15:0] kernel_column_payload;
  logic [1:0][COORD_W-1:0] coordinate_payload;
  logic [31:0] pixel_payload, tap_group_payload, row_group_payload;
  logic [31:0] tap_group_reference, row_group_reference;
  logic [31:0] next_row_group_base;
  logic pad_q;
  logic [31:0] addr;
  logic [p_cache_read_width-1:0] word_buf;
  logic [31:0] word_addr;
  logic word_valid;
  logic [p_cache_read_width-1:0] operation_word_buf;
  logic [31:0] operation_word_addr;
  logic operation_word_valid;
  logic operation_padding;
  logic descriptor_output_available;
  logic descriptor_check;
  logic descriptor_accept_fire;
  logic descriptor_read_fire;
  logic descriptor_early_context;
  logic [2:0] tile_base_context;
  logic descriptor_response_available;
  logic descriptor_preview_safe;
  logic prepared_single_word;
  logic prepared_word_ready;
  logic [31:p_word_shift] prepared_word_tag;
  logic [31:0] incoming_columns;
  logic request_cancel, request_capture_ready;
  logic prepared_read_pending;
  logic active_read_pending;
  st_t operation_state;
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
  logic stream_cache_req_valid;
  logic stream_cache_rsp_ready;
  logic incoming_geometry;
  logic request_tap_context;
  logic cache_rsp_ready;
  logic stream_next_request;
  logic next_row_request, row_request_valid, row_request_padding;
  logic [31:0] row_request_address, row_request_pixel;
  logic [COORD_W-1:0] row_request_y;
  logic request_stream_context;
  logic request_row_context;
  logic request_row_metadata_context;
  logic request_descriptor_metadata_context;
  logic [31:0] unused_geometry_request_index, unused_geometry_request_epoch;
  logic active_after_chunk;
  logic [p_word_shift+1:0] byte_offset_sum;
  logic incoming_context;
  logic incoming_word_hit;
  logic [9:0][1:0] incoming_word_candidates;
  logic finishing_tile;
  logic descriptor_response_forward;
  logic incoming_next_tile_fast, incoming_next_position_fast;
  logic incoming_skip_tap;
  logic [15:0] window_next_x;
  logic [15:0] window_next_y;
  logic [15:0] window_next_ch;
  logic [1:0] incoming_tile_group_fits;
  logic cache_port_valid;
  logic preview_valid_q;
  logic [31:0] cache_req_addr;
  logic [31:0] cache_req_addr_reference;
  logic [31:0] stream_request_addr;
  logic request_pending;
  logic cache_port_ready;
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
  logic [31:0] req_index, request_pixel_value;
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
  logic [9:0][31:0] incoming_pixel_candidates;
  logic [9:0][31:0] incoming_address_candidates;
  logic [9:0][31:0] incoming_group_candidates;
  logic [9:0][15:0] incoming_kernel_x_candidates;
  logic [9:0][COORD_W-1:0] incoming_y_candidates;
  logic [9:0] incoming_pixel_select;
  logic [31:0] request_output_y;
  logic [31:0] request_address_value;
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
  logic committing_padding;
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
  logic stream_row_coordinate_update, stream_row_data_update;
  logic stream_tap_coordinate_update, stream_tap_data_update;
  logic error_next, tile_error_next;
  // 已提交描述符在检查周期即可使用保存字或填充值；输出停顿时继续保留检查状态。
  // 数据、标签和有效位选择相同来源，下一描述符可以继承本次实际输出的数据字。
  assign descriptor_output_available = descriptor_padding || committing_saved_word_hit || committing_live_word_hit;
  assign descriptor_check = state[$clog2(DESCRIPTOR_CHECK)];
  always_comb begin
    operation_state = state;
    if (descriptor_check) begin
      if (active_read_pending) operation_state = WAIT_WORD;
      else if (descriptor_output_available) operation_state = descriptor_padding ? ZERO_STREAM : STREAM;
      else operation_state = FETCH;
    end
  end
  assign operation_word_buf = state[$clog2(DESCRIPTOR_CHECK)] && committing_saved_word_hit ?
      descriptor_word_data_q : word_buf;
  assign operation_word_addr = state[$clog2(DESCRIPTOR_CHECK)] && committing_saved_word_hit ?
      {addr[31:p_word_shift], {p_word_shift{1'b0}}} : word_addr;
  assign operation_word_valid = (state[$clog2(DESCRIPTOR_CHECK)] && committing_saved_word_hit) || word_valid;
  assign operation_padding = state[$clog2(DESCRIPTOR_CHECK)] ? descriptor_padding : pad_q;
  // 每个准备项保存首字请求是否已进入请求寄存器，提交时把响应归属交给运行项。
  // 同周期提交和接收分别读取旧准备标志、写入新准备标志，保持缓存响应顺序。
  assign descriptor_accept_fire = tile_valid && tile_ready;
  assign descriptor_read_fire = REGISTER_DESCRIPTOR && descriptor_accept_fire &&
      descriptor_preview_safe && incoming_fast &&
      !incoming_padding && !incoming_word_hit && tile_rows != RW'(0) &&
      32'(tile_rows) <= SIZE && 32'(tile_cols) <= SIZE && tile_q_before_end &&
      tile_rows_in_range && cache_req_ready;
  // 下一项只有一个输出拍时，其首字就是末字，后续项可复用该待返回字。
  // 多拍项后面的请求在提交后发出，使响应顺序始终与运行项的数据需求相同。
  assign incoming_columns = tile_cols == 0 ? 32'(SIZE) : 32'(tile_cols);
  assign descriptor_preview_safe = !REGISTER_DESCRIPTOR || !tile_prepared_valid ||
      (prepared_single_word && (prepared_read_pending || prepared_word_ready));
  conv_descriptor_read_state #(
    .p_word_shift(p_word_shift), .p_lanes(LANES), .p_narrow_lanes(NARROW_LANES),
    .p_enabled(REGISTER_DESCRIPTOR && REGISTER_CACHE_REQUEST)
  ) u_descriptor_read_state (
    .i_clk(clk), .i_rst_n(rst_n), .i_configure(cfg_valid && cfg_ready), .i_error(error),
    .i_accept(descriptor_accept_fire), .i_commit(tile_commit), .i_read_fire(descriptor_read_fire),
    .i_response_consumed(cache_rsp_valid && cache_rsp_ready), .i_prepared_valid(tile_prepared_valid),
    .i_request_write(request_capture_ready), .i_request_pending(request_pending),
    .i_request_tag(request_addr_q[31:p_word_shift]), .i_incoming_address(incoming_addr),
    .i_columns(incoming_columns), .i_one_row(tile_rows == RW'(1)), .i_narrow(tile_narrow),
    .i_input_s16(c.input_s16), .i_fast(incoming_fast), .i_padding(incoming_padding),
    .i_group_fits(incoming_next_position_fast ? incoming_tile_group_fits[0] : incoming_tile_group_fits[1]),
    .i_word_hit(incoming_word_hit), .o_prepared_pending(prepared_read_pending),
    .o_active_pending(active_read_pending), .o_prepared_tag(prepared_word_tag),
    .o_prepared_word_ready(prepared_word_ready), .o_single_word(prepared_single_word),
    .o_request_cancel(request_cancel)
  );

  conv_im2col_geometry #(
    .p_size(SIZE), .p_slot_w(SLOT_W), .p_lanes(LANES), .p_line_bytes(LINE_BYTES), .p_register_cache_request(REGISTER_CACHE_REQUEST), .p_register_descriptor(REGISTER_DESCRIPTOR), .p_cw(CW)
  ) u_geometry (
    .i_clk(clk),
    .i_rst_n(rst_n),
    .i_cfg_valid(cfg_valid),
    .i_cfg_ready(cfg_ready),
    .i_cfg(cfg),
    .i_state(operation_state),
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
    .o_incoming_req_index(unused_geometry_request_index),
    .o_incoming_req_epoch(unused_geometry_request_epoch),
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
    .i_state(operation_state),
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
    .i_word_buf(operation_word_buf),
    .i_word_addr(operation_word_addr), .i_compare_word_addr(word_addr),
    .i_word_forward(descriptor_check && committing_saved_word_hit),
    .i_word_valid(operation_word_valid),
    .i_incoming_word_hit(incoming_word_hit),
    .i_prepared_word_tag(prepared_word_tag),
    .i_descriptor_response_forward(descriptor_response_available),
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
    .o_incoming_word_candidates(incoming_word_candidates),
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
    .o_committing_padding(committing_padding),
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
    .i_state(operation_state),
    .i_descriptor_check(descriptor_check),
    .i_descriptor_preview_safe(descriptor_preview_safe),
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
    .i_pad_q(operation_padding),
    .o_addr(addr),
    .i_word_buf(operation_word_buf),
    .i_word_addr(operation_word_addr), .i_saved_word_addr(word_addr),
    .i_word_valid(operation_word_valid),
    .o_current_word_hit(current_word_hit),
    .o_chunk_count(chunk_count),
    .i_decode_index(decode_index),
    .i_decode_inner(decode_inner),
    .i_cache_req_ready(cache_req_ready),
    .i_cache_rsp_valid(cache_rsp_valid),
    .i_cache_rsp_error(cache_rsp_failure),
    .o_cache_req_valid(stream_cache_req_valid),
    .o_cache_rsp_ready(stream_cache_rsp_ready),
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
    .i_incoming_word_candidates(incoming_word_candidates), .i_incoming_word_select(incoming_pixel_select),
    .i_incoming_live_word_o_equal(incoming_live_word_o_equal),
    .i_row_base_valid(row_base_valid),
    .i_coordinate_address_valid(coordinate_address_valid),
    .i_row_coordinate_valid(row_coordinate_valid),
    .i_next_row_padding(next_row_padding),
    .i_row_request_valid(row_request_valid), .i_row_request_address(row_request_address),
    .i_row_request_padding(row_request_padding),
    .i_next_tap_padding(next_tap_padding),
    .i_incoming_tap_wrap_q(incoming_tap_wrap_q),
    .i_next_row_addr(next_row_addr),
    .i_next_tap_addr(next_tap_addr),
    .o_next_q_current(next_q_current),
    .i_channel_accept_fire(channel_accept_fire),
    .i_committing_tile_packed(committing_tile),
    .i_tile_commit(tile_commit),
    .i_stream_operation_accept(stream_operation_accept),
    .i_stream_transfer_accept(stream_transfer_accept),
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
  conv_im2col_row_request #(.p_coord_width(COORD_W), .p_enabled(REGISTER_ROW_ADDRESS)) u_row_request (
    .i_clk(clk), .i_rst_n(rst_n), .i_cfg_fire(cfg_valid && cfg_ready), .i_error(error),
    .i_configuration(c), .i_step_phase(address_step_phase), .i_base_valid(row_base_valid),
    .i_coordinate_valid(coordinate_address_valid), .i_geometry(geometry_tile), .i_tile_commit(tile_commit),
    .i_commit_next_row(committing_tile.fast && !committing_tile.invalid && !committing_tile.geometry && committing_tile.operation[5]),
    .i_advance(stream_operation_accept && chunk_reaches_end && !row_last_q),
    .i_row_wrap(row_wrap), .i_output_x(ox_q), .i_second_last_x(second_last_col_q),
    .i_base_address(row_base_addr), .i_base_pixel(row_base_pixel), .i_base_coordinate({row_base_iy, row_base_ix}),
    .i_wrap_dx(row_wrap_dx), .i_pair_dx(row_pair_dx), .i_wrap_pixels(row_wrap_pixels),
    .i_step_bytes(row_step_bytes), .i_wrap_bytes(row_wrap_bytes), .i_next_address(next_row_addr),
    .i_next_pixel(next_row_pixel), .i_next_y(next_row_iy), .i_next_padding(next_row_padding),
    .o_valid(row_request_valid), .o_address(row_request_address), .o_pixel(row_request_pixel),
    .o_y(row_request_y), .o_padding(row_request_padding)
  );
  // 行末的数据来源提前选择，填充和保存字命中只控制实际请求资格。
  assign request_row_metadata_context = row_request_valid &&
      (request_stream_context || operation_state[$clog2(ZERO_STREAM)]) &&
      chunk_reaches_end && !row_last_q && row_base_valid && !geometry_tile;
  assign request_descriptor_metadata_context = incoming_context;
  // 地址、索引与纪元通过同一组上下文选择后进入请求寄存器。
  conv_im2col_request_context #(
    .p_coord_width(COORD_W), .p_line_bytes(LINE_BYTES),
    .p_register_descriptor(REGISTER_DESCRIPTOR)
  ) u_request_context (
    .i_configuration(c), .i_descriptor(request_descriptor_metadata_context),
    .i_row_metadata(request_row_metadata_context), .i_tap(request_tap_context),
    .i_row(request_row_context), .i_stream(request_stream_context),
    .i_select(incoming_pixel_select), .i_address_candidate(incoming_address_candidates),
    .i_pixel_candidate(incoming_pixel_candidates), .i_y_candidate(incoming_y_candidates),
    .i_incoming_address(incoming_addr), .i_incoming_pixel(incoming_pixel),
    .i_incoming_y(incoming_iy), .i_cache_address_reference(cache_req_addr_reference),
    .i_next_tap_address(next_tap_addr), .i_next_row_address(row_request_address),
    .i_stream_address(stream_request_addr), .i_address(addr),
    .i_pixel({pixel_index, next_tap_pixel, row_request_pixel}), .i_y({iy, next_tap_iy, row_request_y}),
    .i_epoch_sum(epoch_o_sum[3:0]), .i_short_pixel(short_pixel_q),
    .i_index_shift(window_index_shift_q), .i_index_valid(window_index_valid_q),
    .i_next_position(incoming_next_position_fast), .i_next_tile(incoming_next_tile_fast),
    .i_row_wrap(row_wrap), .i_window_y(window_next_y),
    .i_output_y(oy), .o_cache_address(cache_req_addr),
    .o_request_address(request_address_value), .o_request_y(request_y),
    .o_output_y(request_output_y), .o_index(req_index), .o_request_pixel(request_pixel_value),
    .o_epoch(req_epoch), .o_index_valid(req_index_valid)
  );

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
  assign stream_response_error = operation_state[$clog2(WAIT_WORD)] && cache_rsp_failure;
  assign stream_output_accept = wr_valid && wr_ready;
  // 描述符资格与输出接收并行计算，运行寄存器在最终边沿选择保存。
  assign stream_operation_accept = stream_output_accept && !descriptor_state_context;
  // 行内或下一行的地址推进由输出接收直接控制，空闲阶段提交保持最高优先级。
  assign stream_transfer_accept = stream_output_accept &&
      !(descriptor_commit_eligible && state[$clog2(IDLE)]);
  conv_im2col_stream_position u_stream_position (
    .i_chunk_end(chunk_reaches_end), .i_row_last(row_last_q),
    .i_row_base_valid(row_base_valid), .i_geometry_tile(geometry_tile),
    .i_row_coordinate_valid(row_coordinate_valid), .i_past_active(past_active_q),
    .i_active_after(active_after_chunk), .i_group_end(group_end_o_equal),
    .i_coordinate_address_valid(coordinate_address_valid),
    .o_row_coordinate(stream_row_coordinate_update), .o_row_data(stream_row_data_update),
    .o_tap_coordinate(stream_tap_coordinate_update), .o_tap_data(stream_tap_data_update)
  );
  conv_im2col_error_update u_error_update (
    .i_state(operation_state), .i_error(error), .i_configuration_complete(cfg_prepare_phase == 4),
    .i_configuration_ok(cfg_ok), .i_cfg_fire(cfg_valid && cfg_ready),
    .i_basic_valid(cfg_basic_valid), .i_tile_commit(tile_commit),
    .i_tile_invalid(committing_tile.invalid), .i_stream_error(stream_response_error),
    .i_stream_accept(stream_operation_accept),
    .o_error(error_next), .o_tile_error(tile_error_next)
  );
  assign finishing_tile=stream_output_accept && wr_last;
  // 描述符在返回阶段选择当前缓存字，描述符接收条件控制保存。
  assign descriptor_response_forward = operation_state[$clog2(WAIT_WORD)];
  // 等待中的运行字可以抑制同字重复请求，数据保存只在实际响应有效时使用返回值。
  assign descriptor_response_available = descriptor_response_forward &&
      (!REGISTER_DESCRIPTOR || cache_rsp_success);
  // 描述符就绪的静态条件共用，配置有效只参与最终接收选择。
  assign tile_ready_static = cfg_prepare_phase==0 && configured && !error &&
                              !pred_busy && !pred_cfg_busy && !pred_cfg_pending && !cache_cfg_pending &&
                              !cache_hint_pending && address_step_phase==0;
  assign tile_admission_ready = tile_ready_static && !cfg_valid;
  conv_im2col_tile_context u_tile_context (
    .i_static_ready(tile_ready_static), .i_idle(state[$clog2(IDLE)]),
    .i_stream(operation_state[$clog2(STREAM)]), .i_zero_stream(operation_state[$clog2(ZERO_STREAM)]),
    .i_wait_word(operation_state[$clog2(WAIT_WORD)]), .i_write_ready(wr_ready),
    .i_row_last(row_last_q), .i_chunk_end(chunk_reaches_end), .o_base(tile_base_context), .o_ready(tile_context_ready)
  );
  // 返回成功只合并已经准备的描述符接收资格。
  assign tile_ready_context = tile_context_ready[0] ||
      (cache_rsp_success && tile_context_ready[1]);
  // 准备队列为空且运行项只剩最后一拍时，描述符准备可与缓存等待或输出背压重叠。
  // 运行项完成后再提交准备项，保持请求返回、地址和输出元数据的先后次序。
  assign descriptor_early_context = REGISTER_DESCRIPTOR && !tile_prepared_valid &&
      tile_ready_static && row_last_q &&
      (operation_state[$clog2(WAIT_WORD)] || operation_state[$clog2(STREAM)] ||
       operation_state[$clog2(ZERO_STREAM)]) && !cache_rsp_failure;
  conv_descriptor_admission #(.p_register_descriptor(REGISTER_DESCRIPTOR)) u_descriptor_admission (
    .i_idle_context(tile_base_context[0]),
    .i_output_context(tile_base_context[1] || (cache_rsp_success && tile_base_context[2])),
    .i_early_output(descriptor_early_context), .i_chunk_end(chunk_reaches_end),
    .i_prepared_valid(tile_prepared_valid),
    .i_commit_context({tile_prepared_valid && !error && wr_valid && wr_ready && row_last_q,
                       tile_prepared_valid && !error && operation_state[$clog2(IDLE)]}),
    .i_fast(incoming_fast), .i_configure(cfg_valid), .o_ready(tile_ready)
  );
  assign busy = !cfg_ready;
  assign wr_valid = operation_state[$clog2(STREAM)] || operation_state[$clog2(ZERO_STREAM)] ||
                    (operation_state[$clog2(WAIT_WORD)] && cache_rsp_success);
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
  // 数据来源由运行阶段提前选择，描述符和输出接收只决定保存时刻。
  assign descriptor_payload_context = state[$clog2(IDLE)] ||
      ((operation_state[$clog2(WAIT_WORD)] || operation_state[$clog2(STREAM)] ||
        operation_state[$clog2(ZERO_STREAM)]) && wr_last);
  conv_full_address_add u_address_pixel_sum (
    .i_a(pixel_product), .i_b(32'(ix)), .o_sum(address_pixel_sum)
  );
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
    if (state[$clog2(ADDRESS_PIXEL)]) pixel_payload = address_pixel_sum;
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

  conv_im2col_payload_select #(.p_register_descriptor(REGISTER_DESCRIPTOR)) u_payload_select (
    .i_state(operation_state), .i_descriptor(descriptor_payload_context),
    .i_select(incoming_pixel_select), .i_kernel_candidate(incoming_kernel_x_candidates),
    .i_group_candidate(incoming_group_candidates), .i_saved_kernel_column(committing_tile.kernel_x),
    .i_chunk_end(chunk_reaches_end), .i_kernel_shape_valid(kernel_shape_o_valid),
    .i_decoded_kernel_column(kernel_decode_column), .i_kernel_decode(k_decode_value),
    .i_decode_inner(decode_inner), .i_initial_kernel_column(kx0),
    .i_kernel_column(kx), .i_tap_wrap(tap_wrap),
    .i_group_base(group_base_addr), .i_next_row_group(next_row_group_base),
    .i_next_tap_address(next_tap_addr), .i_group_reference({row_group_reference, tap_group_reference}),
    .o_kernel_column(kernel_column_payload), .o_group({row_group_payload, tap_group_payload})
  );

  // 请求地址、窗口索引和有效位同时寄存，缓存只接收已保存的完整请求。
  // 输出接收旧请求的同一周期可保存新请求，停顿期间保持全部字段。
  // 错误状态继续接收已经进入缓存的响应，响应数据不产生写输出。
  assign cache_rsp_ready = stream_cache_rsp_ready || error;
  assign incoming_geometry = pred_enabled && (CACHE_POLICY != 3 || !c.windowed) &&
      (tile_cols == 0 || 32'(tile_cols) == SIZE) && tile_p0[3:0] == 0 &&
      tile_q0[3:0] == 0 && tile_group < groups_q;
  conv_im2col_request_pipeline #(
    .p_size(SIZE), .p_count_width(TILE_COUNT_W), .p_word_shift(p_word_shift),
    .p_response_depth(CACHE_RESPONSE_DEPTH), .p_registered(REGISTER_CACHE_REQUEST), .p_lookahead(REGISTER_ROW_ADDRESS)
  ) u_request_pipeline (
    .i_clk(clk), .i_rst_n(rst_n), .i_configure(cfg_valid && cfg_ready), .i_error(error),
    .i_response_failure(cache_rsp_failure), .i_tile_commit(tile_commit), .i_configuration(c),
    .i_request_valid(stream_cache_req_valid), .i_cache_ready(cache_port_ready), .i_cancel(request_cancel),
    .i_address(request_address_value), .i_pixel(request_pixel_value), .i_index_reference(req_index),
    .i_short_pixel(short_pixel_q), .i_index_shift(window_index_shift_q), .i_index_valid(req_index_valid),
    .i_geometry(incoming_context ? incoming_geometry : geometry_tile),
    .i_event_first((incoming_context ? incoming_geometry : geometry_tile) && cache_req_addr[3:0]==0),
    .i_epoch(req_epoch), .i_y(request_y[15:0]), .i_progress(request_output_y),
    .i_stream(request_stream_context), .i_row_eligible(request_row_context), .i_row_wrap(row_wrap),
    .i_narrow(narrow_output), .i_past_active(past_active_q), .i_row(row_idx), .i_rows(rows_q),
    .i_column(col_idx), .i_columns(cols_q), .i_active_columns(active_cols_q),
    .i_channel(ch_q), .i_initial_channel(ch0_q), .i_next_row(next_row_idx),
    .i_next_input_x(next_row_ix[15:0]), .i_output_x(ox_q),
    .i_seed_address(row_request_address), .i_seed_pixel(row_request_pixel),
    .o_request_valid(cache_req_valid), .o_request_ready(cache_req_ready), .o_capture_ready(request_capture_ready),
    .o_cache_valid(cache_port_valid), .o_pending(request_pending), .o_preview_valid(preview_valid_q),
    .o_address(request_addr_q), .o_index(request_index_q), .o_index_valid(request_index_valid_q),
    .o_geometry(request_geometry_q), .o_event_first(request_event_first_q),
    .o_epoch(request_epoch_q), .o_y(request_y_q), .o_progress(request_progress_q)
  );
  conv_read_cache #(.SETS(CACHE_SETS),.WAYS(CACHE_WAYS),.LINE_BYTES(LINE_BYTES),
    .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.READ_WIDTH(p_cache_read_width),.DMA_MAX_BYTES(DMA_MAX_BYTES),
    .DEMAND_DEPTH(CACHE_RESPONSE_DEPTH),
    .p_defer_retire_shift(CACHE_POLICY == 3),
    .p_preview_request(REGISTER_CACHE_REQUEST)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cache_config_valid),.cfg_ready(cache_cfg_ready),
    .cfg_base(c.input_base),.cfg_bytes(tensor_bytes),.cfg_bypass(c.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(c.windowed),.cfg_prefetch_enable(c.prefetch_enable),
    .req_valid(cache_port_valid),.req_ready(cache_port_ready),
    .preview_valid(preview_valid_q),
    .preview_addr(request_addr_q),
    .preview_index_valid(request_index_valid_q),.preview_index(request_index_q),
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
  // 首地址的输出格式与状态同时保存，缓存字命中只控制数据是否可发送。
  if (REGISTER_DESCRIPTOR) begin : g_saved_word_format
    always_ff @(posedge clk or negedge rst_n) begin
      if (!rst_n) word_output_q <= 1'b0;
      else if (state_update) word_output_q <= tile_commit && !committing_tile.invalid && committing_tile.fast ?
          !committing_padding : (selected_state[$clog2(STREAM)] || selected_state[$clog2(WAIT_WORD)]);
    end
  end else begin : g_direct_word_format
    assign word_output_q = operation_state[$clog2(STREAM)] || operation_state[$clog2(WAIT_WORD)];
  end
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
       ((operation_state[$clog2(WAIT_WORD)] || operation_state[$clog2(STREAM)] || operation_state[$clog2(ZERO_STREAM)]) && wr_last));

  // 描述符字段提前决定候选状态，接收事件控制保存。
  conv_im2col_descriptor_state #(.p_register_descriptor(REGISTER_DESCRIPTOR)) u_descriptor_state (
    .i_invalid(committing_tile.invalid), .i_fast(committing_tile.fast),
    .i_padding(committing_tile.padding), .i_word_hit(committing_tile.word_hit),
    .i_cache_req_ready(cache_req_ready), .o_state(descriptor_state)
  );

  conv_im2col_state_control #(.p_count_width(TILE_COUNT_W)) u_state_control (
    .i_state(operation_state), .i_descriptor_state(descriptor_state),
    .i_stream_state(stream_advance_state), .i_descriptor_context(descriptor_state_context),
    .i_descriptor_eligible(descriptor_commit_eligible), .i_tile_commit(tile_commit),
    .i_descriptor_padding(descriptor_padding), .i_saved_word_hit(committing_saved_word_hit),
    .i_live_word_hit(committing_live_word_hit), .i_fast_position_valid(p_fast_valid),
    .i_group_shape_valid(group_shape_o_valid), .i_kernel_shape_valid(kernel_shape_o_valid),
    .i_group_channels(c.group_c), .i_kernel_width(c.kernel_w),
    .i_position(p0), .i_reduction(q0),
    .i_tap(tap0), .i_decode_index(decode_index),
    .i_position_valid(address_position_valid), .i_geometry_tile(geometry_tile),
    .i_column(col_idx), .i_predictor_busy(pred_busy),
    .i_hint_pending(cache_hint_pending), .i_word_hit(current_word_hit),
    .i_request_ready(cache_req_ready), .i_response_failure(cache_rsp_failure),
    .i_stream_error(stream_response_error), .i_output_accept(stream_output_accept),
    .i_cfg_valid(cfg_valid), .i_cfg_ready(cfg_ready),
    .o_selected_state(selected_state), .o_state_update(state_update)
  );

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

  conv_im2col_wrap_state u_wrap_state (
    .clk(clk), .rst_n(rst_n),
    .i_cfg_valid(cfg_valid), .i_cfg_ready(cfg_ready),
    .i_state(operation_state), .i_tile_commit(tile_commit),
    .i_descriptor_invalid(committing_tile.invalid), .i_descriptor_fast(committing_tile.fast),
    .i_position_update(committing_tile.output_position_update), .i_stream_error(stream_response_error),
    .i_stream_accept(stream_operation_accept), .i_chunk_end(chunk_reaches_end),
    .i_row_last(row_last_q), .i_past_active(past_active_q),
    .i_active_after(active_after_chunk), .i_group_end(group_end_o_equal),
    .i_row_wrap(row_wrap), .i_tap_wrap(tap_wrap),
    .i_fast_position_valid(p_fast_valid), .i_decode_index(decode_index),
    .i_position(p0), .i_tap(tap0),
    .i_kernel_shape_valid(kernel_shape_o_valid), .i_kernel_width(c.kernel_w),
    .i_row_candidate(row_wrap_candidate), .i_tap_candidate(tap_wrap_candidate),
    .o_wrap({incoming_tap_wrap_q, tap_wrap_q, row_wrap_q})
  );

  // 配置、分块和地址阶段的数据由独立寄存器模块保存。
  conv_im2col_runtime_registers #(
    .p_size(SIZE), .p_slot_width(SLOT_W), .p_count_width(TILE_COUNT_W),
    .p_chunk_width(CHUNK_COUNT_W), .p_coord_width(COORD_W), .p_read_width(p_cache_read_width),
    .p_word_shift(p_word_shift), .p_row_high_width(p_row_high_w), .p_cache_sets(CACHE_SETS),
    .p_cache_ways(CACHE_WAYS), .p_saved_group_lanes(p_saved_group_lanes),
    .p_register_descriptor(REGISTER_DESCRIPTOR), .p_prepared_tile_width($bits(prepared_tile_t))
  ) u_runtime_registers (
    .i_state(operation_state),
    .i_descriptor_check(descriptor_check),
    .o_descriptor_index({tap0, q0, p0}), .o_group_advance({skip_group_q, next_group_q}),
    .o_output_count({active_cols_q, cols_q, rows_q, col_idx, row_idx}), .o_output_coordinate({oy_q, ox_q}),
    .o_kernel_coordinate({kx0_q, ky0_q, kx_q, ky_q}), .o_group_base({row_group_base, tap_group_base}),
    .o_input_coordinate({iy, ix}), .o_history_coordinate({last_y, last_x}),
    .o_wrap_dx({tap_wrap_dx, row_wrap_dx}), .o_axis_pixels({tap_y_pixels, row_y_pixels}),
    .o_wrap_pixels({tap_wrap_pixels, row_wrap_pixels}), .o_step_bytes({tap_step_bytes, row_step_bytes}),
    .o_wrap_bytes({tap_wrap_bytes, row_wrap_bytes}), .o_row_coordinate({row_base_iy, row_base_ix}),
    .o_coordinate_valid({row_coordinate_valid, coordinate_address_valid, row_base_valid}),
    .o_decode({decode_inner, decode_outer, decode_index}), .o_address_product({channel_product, pixel_product}),
    .i_initial_group({cfg_skip_group, cfg_next_group}),
    .i_stream_update({stream_tap_data_update, stream_tap_coordinate_update, stream_row_data_update, stream_row_coordinate_update}),
    .i_group_payload({row_group_payload, tap_group_payload}),
    .i_next_row_coordinate({next_row_iy, next_row_ix}),
    .i_decode_advance({decode_inner_advance, decode_index_advance}), .i_fast_coordinate({p_fast_y, p_fast_x}),
    .i_wrap_pixel_sum({tap_wrap_pixel_sum, row_wrap_pixel_sum}), .i_active_after_chunk(active_after_chunk),
    .i_addr(addr), .i_address_position_valid(address_position_valid), .i_cache_hint_pending(cache_hint_pending),
    .i_cache_rsp_data(cache_rsp_data), .i_cfg(cfg), .i_cfg_input_bytes(cfg_input_bytes), .i_cfg_ok(cfg_ok),
    .i_cfg_positions(cfg_positions), .i_cfg_prepare_phase(cfg_prepare_phase), .i_cfg_ready(cfg_ready),
    .i_cfg_red(cfg_red), .i_cfg_sched_groups(cfg_sched_groups), .i_cfg_valid(cfg_valid),
    .i_channel_addr(channel_addr), .i_chunk_count(chunk_count), .i_chunk_reaches_end(chunk_reaches_end),
    .clk(clk), .i_committing_saved_word_hit(committing_saved_word_hit), .i_committing_tile(committing_tile),
    .i_coordinate_low_difference(coordinate_low_difference), .i_coordinate_payload(coordinate_payload),
    .i_coordinate_product_sum(coordinate_product_sum), .i_current_q_div3(current_q_div3),
    .i_current_q_remainder(current_q_remainder), .i_decode_end_o_equal(decode_end_o_equal),
    .i_descriptor_padding(descriptor_padding), .i_descriptor_word_data(descriptor_word_data_q),
    .i_finishing_tile(finishing_tile), .i_group_address_sum(group_address_sum),
    .i_group_end_o_equal(group_end_o_equal), .i_group_range_channel(group_range_channel),
    .i_group_shape_o_valid(group_shape_o_valid), .i_group_width_shift(group_width_shift),
    .i_history_limit_carry(history_limit_carry), .i_k_decode_value(k_decode_value),
    .i_kernel_column_payload(kernel_column_payload), .i_kernel_decode_column(kernel_decode_column),
    .i_kernel_shape_o_valid(kernel_shape_o_valid), .i_kernel_width_shift(kernel_width_shift),
    .i_next_q_current(next_q_current), .i_next_row_addr(next_row_addr), .i_next_row_idx(next_row_idx),
    .i_next_row_last(next_row_last), .i_next_row_padding(next_row_padding), .i_next_row_pixel(next_row_pixel),
    .i_next_tap_padding(next_tap_padding), .i_p_cache_select(p_cache_select), .i_p_fast_valid(p_fast_valid),
    .i_pixel_payload(pixel_payload), .i_position_high_minus_one(position_high_minus_one),
    .i_pred_busy(pred_busy), .i_pred_done(pred_done), .i_pred_rank(pred_rank), .i_pred_start(pred_start),
    .i_row_pair_dx_sum(row_pair_dx_sum), .i_row_wrap(row_wrap), .rst_n(rst_n),
    .i_shared_channel_product(shared_channel_product), .i_shared_coordinate_product(shared_coordinate_product),
    .i_stream_operation_accept(stream_operation_accept), .i_stream_response_error(stream_response_error),
    .i_tap_wrap(tap_wrap), .i_tile_commit(tile_commit), .i_wr_ready(wr_ready), .i_wr_valid(wr_valid),
    .o_address_step_phase(address_step_phase), .o_configuration(c), .o_initial_channel(ch0_q), .o_configured(configured),
    .o_coordinate_borrow(coordinate_borrow_q), .o_coordinate_product(coordinate_product_q),
    .o_coordinate_sum(coordinate_sum_q), .o_fragment_image_fits(fragment_image_fits),
    .o_geometry_tile(geometry_tile), .o_group_base_addr(group_base_addr), .o_group_count(groups_q),
    .o_history_position(last_p), .o_history_overflow(last_p_overflow_q), .o_history_position_valid(last_p_valid),
    .o_line_hint_rank(line_hint_rank), .o_line_hint_valid(line_hint_valid), .o_narrow_output(narrow_output),
    .o_history_valid(p_cache_valid), .o_padding(pad_q), .o_past_active(past_active_q), .o_pixel_index(pixel_index),
    .o_position_count(position_count), .o_position_high_minus_one(position_high_minus_one_q),
    .o_reduction_index(q_current), .o_reduction_len(reduction_len), .o_row_base_addr(row_base_addr),
    .o_row_base_pixel(row_base_pixel), .o_row_last(row_last_q), .o_row_pair_dx(row_pair_dx), .o_slot(slot_q),
    .o_tensor_bytes(tensor_bytes), .o_tile_done(tile_done), .o_word_addr(word_addr), .o_word_data(word_buf),
    .o_word_valid(word_valid)
  );
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
`default_nettype wire
