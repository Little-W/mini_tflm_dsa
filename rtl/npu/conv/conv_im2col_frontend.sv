// SPDX-License-Identifier: Apache-2.0
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
  parameter int DMA_MAX_BYTES=256*(BUS_WIDTH/8),
  parameter int CACHE_POLICY=3,
  parameter int CW=$clog2(SIZE),
  parameter int RW=$clog2(SIZE+1)
) (
  input logic clk, rst_n,
  input logic cfg_valid,
  output logic cfg_ready,
  input conv_im2col_pkg::conv_cfg_t cfg,
  // Native IA scheduler context. Zero groups disables the geometry policy for
  // standalone clients that do not promise the native descriptor order.
  input logic [31:0] cfg_sched_r = 32'd0,
  input logic [31:0] cfg_sched_groups = 32'd0,
  input logic tile_valid,
  output logic tile_ready,
  input logic [31:0] tile_p0, tile_q0,
  input logic [RW-1:0] tile_rows,
  input logic [RW-1:0] tile_cols = '0, // Zero selects the full SIZE columns.
  input logic [SLOT_W-1:0] tile_slot,
  input logic [31:0] tile_group = 32'd0,
  output logic wr_valid,
  input logic wr_ready,
  output logic [SLOT_W-1:0] wr_slot,
  output logic [CW-1:0] wr_row, wr_col,
  output logic signed [15:0] wr_data [LANES],
  output logic [LANES-1:0] wr_mask,
  output logic tile_done, tile_error, error, busy,
  output logic wr_last,
  output logic arvalid,
  input logic arready,
  output logic [31:0] araddr,
  output logic [7:0] arlen,
  output logic [2:0] arsize,
  output logic [1:0] arburst,
  input logic rvalid,
  output logic rready,
  input logic [BUS_WIDTH-1:0] rdata,
  input logic [1:0] rresp,
  input logic rlast
);
  import conv_im2col_pkg::*;
  typedef enum logic [4:0] {IDLE, P_DECODE, P_START, P_WAIT, Q_DECODE, Q_START, Q_WAIT,
    K_DECODE, K_START, K_WAIT, COORD, COORD_SUM, COORD_PAD, ADDRESS, ADDRESS_PIXEL,
    ADDRESS_PRODUCT, ADDRESS_BASE, ADDRESS_CHANNEL, FETCH, WAIT_WORD, STREAM, ZERO_STREAM} st_t;
  // 主状态机采用声明中的五位二进制编码。
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
  logic [15:0] group_minus_two_q, group_minus_three_q;
  logic [LANES-1:0] group_lane_allowed;
  logic [3:0] group_range_q, group_range_cfg;
  logic [5:0][15:0] group_range_channel;
  logic [5:0][3:0] group_range_next;
  logic [31:0] p0, q0, tap0;
  logic [32:0] next_group_q;
  logic [TILE_COUNT_W-1:0] row_idx, col_idx, rows_q, cols_q, active_cols_q;
  logic [TILE_COUNT_W-1:0] next_row_idx;
  logic row_last_q, next_row_last;
  logic unused_row_index_carry;
  logic [TILE_COUNT_W-1:0] col_remaining, active_remaining;
  logic [16:0] group_remaining;
  logic [LANES-1:0] chunk_lane_allowed, word_lane_allowed, chunk_end_lane;
  logic chunk_reaches_end;
  logic [15:0] ox_q, oy_q, ky_q, kx_q, ch_q, ky0_q, kx0_q, ch0_q;
  wire [31:0] ox=32'(ox_q), oy=32'(oy_q), ky=32'(ky_q), kx=32'(kx_q), ch=32'(ch_q);
  wire [31:0] ky0=32'(ky0_q), kx0=32'(kx0_q), ch0=32'(ch0_q);
  logic [32:0] q_current;
  localparam int COORD_W=35;
  localparam logic signed [COORD_W-1:0] p_coord_max = {1'b0,{(COORD_W-1){1'b1}}};
  logic signed [COORD_W-1:0] ix, iy;
  logic ix_step_below_limit;
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
  logic [31:0] word_buf, word_addr;
  logic word_valid;
  logic [CHUNK_COUNT_W-1:0] chunk_count;
  logic [SLOT_W-1:0] slot_q;
  logic [31:0] decode_index, decode_outer, decode_inner;
  logic [2:0][31:0] decode_end_i_target;
  logic [2:0] decode_end_o_equal;
  logic cache_cfg_ready, cache_req_ready, cache_rsp_valid, cache_rsp_error;
  localparam bit p_cfg_idle_use_lut =
`ifdef ASIC_SYNTHESIS
    1'b0;
`elsif XILINX_FPGA
    1'b1;
`else
    1'b0;
`endif
  logic cache_req_valid, cache_rsp_ready, stream_next_request,stream_context;
  logic [3:0] byte_offset_sum;
  logic word_boundary;
  logic incoming_request, incoming_context, incoming_word_hit, finishing_tile;
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
  logic [31:0] cache_rsp_data;
  logic [31:0] selected_word;
  logic [31:0] stream_word;
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
  logic [15:0] p_delta;
  localparam bit p_row_end_use_lut =
`ifdef ASIC_SYNTHESIS
    1'b0;
`elsif XILINX_FPGA
    1'b1;
`else
    1'b0;
`endif
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
  logic [2:0][15:0] retirement_row;
  logic [2:0][31:0] retirement_value;
  logic req_index_valid,window_index_valid_q;
  logic [4:0] window_index_shift_q;
  logic pf_valid, pf_ready;
  logic [31:0] pf_addr, pf_index, pf_epoch, pf_retire;
  logic pf_index_valid;
  logic [3:0] prefetch_phase;
  logic [31:0] pf_distance_q, pf_step_q, pf_address_calc, pf_channel_product;
  logic pf_offer_valid;
  wire prefetch_active = prefetch_phase!=0;
  logic signed [COORD_W-1:0] pfa_x, pfa_y;
  logic [31:0] pfa_channel, pfa_origin_channel, pfa_output_x, pfa_output_y;
  logic [31:0] pfa_kernel_x, pfa_rows, pfa_cols;
  logic [31:0] pfa_ref_addr, pfa_ref_index, pfa_ref_epoch, pfa_retire;
  logic pfa_ref_index_valid;
  logic [31:0] pf0_x, pf0_y, pf0_channel, pf0_epoch;
  logic [31:0] pf0_ref_addr, pf0_ref_index, pf0_ref_epoch, pf0_ref_retire;
  logic pf0_ref_index_valid, pf0_fragment, pf0_coordinate_valid;
  logic [31:0] pf1_pixel, pf1_channel, pf1_epoch, pf1_retire;
  logic [31:0] pf1_ref_addr, pf1_ref_index, pf1_ref_epoch, pf1_ref_retire;
  logic pf1_ref_index_valid, pf1_fragment, pf1_coordinate_valid;
  logic [31:0] pf_x, pf_y, pf_step, pf_channel, pf_distance;
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
  logic [2:0] next_word_low_sum;
  logic [2:0] incoming_step_low_sum, incoming_wrap_low_sum;
  logic [29:0] next_word_i_a, next_word_i_b, next_word_i_target;
  logic next_word_i_carry_in, next_word_o_equal;
  logic [29:0] incoming_word_i_a, incoming_word_i_b, incoming_word_i_target;
  logic incoming_word_i_carry_in, incoming_word_o_equal;
  logic [29:0] incoming_live_word_i_target;
  logic incoming_live_word_o_equal;
  logic [1:0] address_step_phase;
  logic signed [32:0] row_wrap_dx, tap_wrap_dx;
  logic signed [32:0] row_y_pixels, tap_y_pixels, row_wrap_pixels, tap_wrap_pixels;
  logic [31:0] row_step_bytes, tap_step_bytes, row_wrap_bytes, tap_wrap_bytes, group_bytes;
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
  logic channel_descriptor_valid, channel_accept_fire, tile_ready_context;
  logic [15:0] channel_update, channel_value;
  logic [5:0] channel_accept_i_flags;

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
    if (p_cfg_idle_use_lut && p_row_high_w <= 27) begin : g_high_range_lut
      logic [26:0] row_high_i_a, row_high_i_b, row_high_i_last;
      logic [8:0] leaf_before, leaf_equal, leaf_last_equal;
      logic [2:0] group_before, group_equal;
      logic [5:0] result_i_flags;

      // 每三位并行比较，再按高位优先合并；二十七位范围保持三级逻辑。
      assign row_high_i_a = 27'(tile_p0[31:p_row_low_w]);
      assign row_high_i_b = 27'(position_count[31:p_row_low_w]);
      assign row_high_i_last = 27'(position_high_minus_one_q);
      assign high_before_end_by_one = &leaf_last_equal;
      for (genvar part = 0; part < 9; part++) begin : g_leaf
        logic [5:0] compare_i_bits, last_i_bits;
        assign compare_i_bits = {row_high_i_b[3*part +: 3], row_high_i_a[3*part +: 3]};
        assign last_i_bits = {row_high_i_last[3*part +: 3], row_high_i_a[3*part +: 3]};
        LUT6 #(.INIT(64'h7F3F_1F0F_0703_0100)) u_before (
          .I0(compare_i_bits[0]), .I1(compare_i_bits[1]), .I2(compare_i_bits[2]),
          .I3(compare_i_bits[3]), .I4(compare_i_bits[4]), .I5(compare_i_bits[5]),
          .O(leaf_before[part])
        );
        LUT6 #(.INIT(64'h8040_2010_0804_0201)) u_equal (
          .I0(compare_i_bits[0]), .I1(compare_i_bits[1]), .I2(compare_i_bits[2]),
          .I3(compare_i_bits[3]), .I4(compare_i_bits[4]), .I5(compare_i_bits[5]),
          .O(leaf_equal[part])
        );
        LUT6 #(.INIT(64'h8040_2010_0804_0201)) u_last_equal (
          .I0(last_i_bits[0]), .I1(last_i_bits[1]), .I2(last_i_bits[2]),
          .I3(last_i_bits[3]), .I4(last_i_bits[4]), .I5(last_i_bits[5]),
          .O(leaf_last_equal[part])
        );
      end
      for (genvar part = 0; part < 3; part++) begin : g_group
        logic [5:0] merge_i_flags;
        assign merge_i_flags = {1'b0, leaf_equal[3*part+2], leaf_equal[3*part+1],
          leaf_before[3*part+2], leaf_before[3*part+1], leaf_before[3*part]};
        assign group_equal[part] = &leaf_equal[3*part +: 3];
        LUT6 #(.INIT(64'hFEFC_F0F0_FEFC_F0F0)) u_before (
          .I0(merge_i_flags[0]), .I1(merge_i_flags[1]), .I2(merge_i_flags[2]),
          .I3(merge_i_flags[3]), .I4(merge_i_flags[4]), .I5(merge_i_flags[5]),
          .O(group_before[part])
        );
      end
      assign result_i_flags = {1'b0, group_equal[2], group_equal[1], group_before};
      assign high_at_end = &group_equal;
      LUT6 #(.INIT(64'hFEFC_F0F0_FEFC_F0F0)) u_before (
        .I0(result_i_flags[0]), .I1(result_i_flags[1]), .I2(result_i_flags[2]),
        .I3(result_i_flags[3]), .I4(result_i_flags[4]), .I5(result_i_flags[5]),
        .O(high_before_end)
      );
    end else begin : g_high_range_logic
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
    logic [COORD_W-9:0] coordinate_high_zero, coordinate_high_one;
    logic unused_coordinate_zero_carry, unused_coordinate_one_carry;
    logic byte_low_before, byte_high_zero_before, byte_high_one_before;
    logic low_carry, low_before, high_o_equal;

    // 高字节分别计算两种进位及边界关系，低字节只选择最终结果。
    assign byte_low_sum = {1'b0, bound_a[axis][7:0]} + {1'b0, bound_b[axis][7:0]};
    assign byte_high_zero = {1'b0, bound_a[axis][15:8]} + {1'b0, bound_b[axis][15:8]};
    assign byte_high_one = {1'b0, bound_a[axis][15:8]} + {1'b0, bound_b[axis][15:8]} + 9'd1;
    assign {unused_coordinate_zero_carry, coordinate_high_zero} =
      {1'b0, bound_a[axis][COORD_W-1:8]} + {1'b0, bound_b[axis][COORD_W-1:8]};
    assign {unused_coordinate_one_carry, coordinate_high_one} =
      {1'b0, bound_a[axis][COORD_W-1:8]} + {1'b0, bound_b[axis][COORD_W-1:8]} + (COORD_W-7)'(1);
    assign bound_sum[axis] = {
      byte_low_sum[8] ? coordinate_high_one : coordinate_high_zero, byte_low_sum[7:0]};
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

  // 数据字匹配只需要高三十位的加法等式，低两位单独提供进位。
  assign next_tap_delta = tap_wrap ? tap_wrap_bytes : tap_step_bytes;
  assign next_word_low_sum = {1'b0, tap_group_base[1:0]} + {1'b0, next_tap_delta[1:0]};
  assign next_word_i_a = tap_group_base[31:2];
  assign next_word_i_b = next_tap_delta[31:2];
  assign next_word_i_target = addr[31:2];
  assign next_word_i_carry_in = next_word_low_sum[2];
  add_equal #(.p_width(30)) u_next_word (
    .i_a(next_word_i_a), .i_b(next_word_i_b), .i_target(next_word_i_target),
    .i_carry_in(next_word_i_carry_in), .o_equal(next_word_o_equal)
  );
  // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。
  assign incoming_step_low_sum = {1'b0, row_base_addr[1:0]} + {1'b0, tap_step_bytes[1:0]};
  assign incoming_wrap_low_sum = {1'b0, row_base_addr[1:0]} + {1'b0, tap_wrap_bytes[1:0]};
  assign incoming_word_i_a = row_base_addr[31:2];
  assign incoming_word_i_b = incoming_delta[31:2];
  assign incoming_word_i_target = word_addr[31:2];
  add_equal #(.p_width(30), .p_use_lut(p_cfg_idle_use_lut)) u_incoming_word (
    .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_word_i_target),
    .i_carry_in(incoming_word_i_carry_in), .o_equal(incoming_word_o_equal)
  );
  // 两个来源的数据字提前完成比较，当前传输的完成条件只选择一位命中结果。
  assign incoming_live_word_i_target = addr[31:2];
  add_equal #(.p_width(30), .p_use_lut(p_cfg_idle_use_lut)) u_incoming_live_word (
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
    assign address_low = {1'b0, addr[p_step_width-1:0]} + {1'b0, byte_step};
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

  // Configuration-time products leave only additions and bounds checks at
  // row and tap boundaries while the current word is being transferred.
  assign row_wrap = row_wrap_q;
  assign tap_wrap = tap_wrap_q;
  always_comb begin
    next_row_ix = $signed(bound_sum[0]);
    next_row_iy = $signed(bound_sum[1]);
    next_row_pixel=row_base_pixel+32'($unsigned(row_wrap ? row_wrap_pixels : $signed(33'(c.stride_w))));
    next_row_addr=row_base_addr+(row_wrap ? row_wrap_bytes : row_step_bytes);
    next_row_group_base=row_group_base+(row_wrap ? row_wrap_bytes : row_step_bytes);
    // 有效图像坐标的高位必须全为零，低十六位再与图像尺寸比较。
    next_row_padding = !bound_valid[0] || !bound_valid[1];
    // 配置阶段保存卷积核末列，当前列判断不再经过加一进位。
    next_tap_ix = $signed(bound_sum[2]);
    next_tap_iy = $signed(bound_sum[3]);
    next_tap_pixel=pixel_index+32'($unsigned(tap_wrap ? tap_wrap_pixels : $signed(33'(c.dilation_w))));
    next_tap_addr=tap_group_base+(tap_wrap ? tap_wrap_bytes : tap_step_bytes);
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
  // 形状判断与配置同时保存，后续解码直接使用对应配置的寄存结果。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      group_shape_o_valid <= 1'b0;
      kernel_shape_o_valid <= 1'b0;
    end else if (cfg_valid && cfg_ready) begin
      group_shape_o_valid <= group_shape_check_o_valid;
      kernel_shape_o_valid <= kernel_shape_check_o_valid;
    end
  end
  function automatic logic [4:0] power_shift(input logic [31:0] value);
    logic [4:0] result;
    result=0;
    for (int b=0;b<32;b++) if (value[b]) result=5'(b);
    return result;
  endfunction
  // 请求先选择输入行，再共用计算；预取的两个阶段各自保留独立结果。
  assign retirement_row[0] = request_pending ? request_y_q : iy[15:0];
  assign retirement_row[1] = pfa_y[15:0];
  assign retirement_row[2] = pf0_y[15:0];
  for (genvar row_port = 0; row_port < 3; row_port++) begin : g_retirement
    logic [16:0] padded_row, shifted_row, incremented_row;
    logic unused_increment_carry;
    logic [16:0] bounded_row;

    // 行递增与上限比较并行，最后选择限幅结果，避免串联两次范围比较。
    assign padded_row = {1'b0, retirement_row[row_port]} + {1'b0, c.pad_top};
    assign shifted_row = padded_row >> retire_shift_q;
    localparam bit p_increment_use_lut =
`ifdef ASIC_SYNTHESIS
      1'b0;
`elsif XILINX_FPGA
      1'b1;
`else
      1'b0;
`endif
    if (p_increment_use_lut) begin : g_increment_lut
      localparam logic [6:0][4:0] p_pair_low = {5'd14, 5'd12, 5'd10, 5'd8, 5'd6, 5'd2, 5'd0};
      localparam logic [2:0][4:0] p_single_bit = {5'd16, 5'd5, 5'd4};
      localparam logic [63:0] p_pair_increment = 64'h6ccc_cccc_5aaa_aaaa;
      localparam logic [1:0][63:0] p_range_all = {64'h8000_8000_8888_8888, 64'h8000_0000_8080_8080};
      logic [1:0][5:0] prefix_i_bits;
      logic [1:0] prefix_o_all;
      logic [1:0][4:0] range_i_bits;
      logic [1:0][1:0] range_o_all;
      logic [6:0][4:0] pair_i_bits;
      logic [2:0][5:0] single_i_bits;
      logic increment_i_one;

      // 低五位进位含递增使能，各个高位区间独立检查，所有结果最多经过两级查找表。
      assign increment_i_one = 1'b1;
      assign prefix_i_bits[0] = {short_pixel_q, shifted_row[4:0]};
      assign prefix_i_bits[1] = {1'b1, shifted_row[14:10]};
      for (genvar prefix_index = 0; prefix_index < 2; prefix_index++) begin : g_prefix
        LUT6 #(.INIT(64'h8000_0000_0000_0000)) u_all (
          .I0(prefix_i_bits[prefix_index][0]), .I1(prefix_i_bits[prefix_index][1]),
          .I2(prefix_i_bits[prefix_index][2]), .I3(prefix_i_bits[prefix_index][3]),
          .I4(prefix_i_bits[prefix_index][4]), .I5(prefix_i_bits[prefix_index][5]),
          .O(prefix_o_all[prefix_index])
        );
      end
      assign range_i_bits[0] = shifted_row[9:5];
      assign range_i_bits[1] = {1'b1, shifted_row[13:10]};
      for (genvar range_index = 0; range_index < 2; range_index++) begin : g_range
        LUT6_2 #(.INIT(p_range_all[range_index])) u_all (
          .I0(range_i_bits[range_index][0]), .I1(range_i_bits[range_index][1]),
          .I2(range_i_bits[range_index][2]), .I3(range_i_bits[range_index][3]),
          .I4(range_i_bits[range_index][4]), .I5(increment_i_one),
          .O5(range_o_all[range_index][0]), .O6(range_o_all[range_index][1])
        );
      end

      // 相邻结果共享低位进位条件，五个输入以内的两位结果共用一个物理查找表。
      assign pair_i_bits[0] = {2'b11, short_pixel_q, shifted_row[1:0]};
      assign pair_i_bits[1] = {shifted_row[1:0], short_pixel_q, shifted_row[3:2]};
      assign pair_i_bits[2] = {1'b1, shifted_row[5], prefix_o_all[0], shifted_row[7:6]};
      assign pair_i_bits[3] = {1'b1, range_o_all[0][0], prefix_o_all[0], shifted_row[9:8]};
      assign pair_i_bits[4] = {1'b1, range_o_all[0][1], prefix_o_all[0], shifted_row[11:10]};
      assign pair_i_bits[5] = {range_o_all[1][0], range_o_all[0][1], prefix_o_all[0], shifted_row[13:12]};
      assign pair_i_bits[6] = {range_o_all[1][1], range_o_all[0][1], prefix_o_all[0], shifted_row[15:14]};
      for (genvar pair_index = 0; pair_index < 7; pair_index++) begin : g_pair
        localparam int p_low = int'(p_pair_low[pair_index]);
        LUT6_2 #(.INIT(p_pair_increment)) u_increment (
          .I0(pair_i_bits[pair_index][0]), .I1(pair_i_bits[pair_index][1]),
          .I2(pair_i_bits[pair_index][2]), .I3(pair_i_bits[pair_index][3]),
          .I4(pair_i_bits[pair_index][4]), .I5(increment_i_one),
          .O5(incremented_row[p_low]), .O6(incremented_row[p_low+1])
        );
      end
      assign single_i_bits[0] = {shifted_row[3:0], short_pixel_q, shifted_row[4]};
      assign single_i_bits[1] = {4'b1111, prefix_o_all[0], shifted_row[5]};
      assign single_i_bits[2] = {1'b1, shifted_row[15], prefix_o_all[1], range_o_all[0][1], prefix_o_all[0], shifted_row[16]};
      for (genvar single_index = 0; single_index < 3; single_index++) begin : g_single
        localparam int p_bit = int'(p_single_bit[single_index]);
        LUT6 #(.INIT(64'h6aaa_aaaa_aaaa_aaaa)) u_increment (
          .I0(single_i_bits[single_index][0]), .I1(single_i_bits[single_index][1]),
          .I2(single_i_bits[single_index][2]), .I3(single_i_bits[single_index][3]),
          .I4(single_i_bits[single_index][4]), .I5(single_i_bits[single_index][5]),
          .O(incremented_row[p_bit])
        );
      end
      assign unused_increment_carry = short_pixel_q && (&shifted_row);
    end else begin : g_increment_logic
      assign {unused_increment_carry, incremented_row} = {1'b0, shifted_row} + {17'd0, short_pixel_q};
    end
    assign bounded_row = shifted_row < {1'b0, retire_last_row_q} ?
        incremented_row : {1'b0, retire_last_row_q};
    assign retirement_value[row_port] = retire_enabled_q ? {15'd0, bounded_row} : 32'hffff_ffff;
  end
  assign request_retire = retirement_value[0];
  assign pfa_retire = retirement_value[1];
  assign pf_retire = retirement_value[2];

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
  assign p_delta = 16'(p_decode - last_p);
  assign p_sum = {1'b0, last_x} + {1'b0, p_delta};
  // 行尾等式直接压缩位置差和历史列数，逐位比较与坐标加减并行。
  assign p_sum_wrap_i_a = last_x ^ p_decode[15:0] ^ ~last_p[15:0];
  assign p_sum_wrap_carry = (last_x & p_decode[15:0]) |
    ((last_x | p_decode[15:0]) & ~last_p[15:0]);
  assign {unused_p_sum_wrap_carry, p_sum_wrap_i_b} = {p_sum_wrap_carry, 1'b1};
  assign p_sum_wrap_i_target = last_output_col_q + c.output_w;
  assign p_sum_wrap_i_carry_in = 1'b0;
  add_equal #(.p_width(16), .p_use_lut(p_row_end_use_lut)) u_p_sum_wrap (
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
  add_equal #(.p_width(16), .p_use_lut(p_row_end_use_lut)) u_p_sum_last (
    .i_a(p_sum_last_i_a), .i_b(p_sum_last_i_b), .i_target(p_sum_last_i_target),
    .i_carry_in(p_sum_last_i_carry_in), .o_equal(p_sum_last_o_equal)
  );
  always_comb begin
    p_fast_valid=0;p_fast_y=0;p_fast_x=0;
    p_fast_wrap = c.output_w != 16'd0 && last_output_col_q == 16'd0;
    if (p_decode==0) p_fast_valid=1;
    else if (p_cache_valid[p_cache_select] && p_cache_key[p_cache_select]==p_decode) begin
      p_fast_valid=1;p_fast_y=32'(p_cache_y[p_cache_select]);p_fast_x=32'(p_cache_x[p_cache_select]);
      p_fast_wrap = c.output_w != 16'd0 && p_cache_x[p_cache_select] == last_output_col_q;
    end else if (last_p_valid && p_decode>=last_p && p_decode<=last_p_limit) begin
      p_fast_valid=1;p_fast_y=32'(last_y);p_fast_x=32'(p_sum);
      // 模和值等于目标时，历史列数与目标的关系直接给出最高位进位。
      p_fast_wrap = c.output_w != 16'd0 &&
        ((p_sum_last_o_equal && last_x <= p_sum_last_i_target) ||
         (p_sum_wrap_o_equal && (!last_output_col_q[15] || last_x > p_sum_wrap_i_target)));
      if (p_sum>={1'b0,c.output_w}) begin p_fast_x=32'(p_sum-{1'b0,c.output_w});p_fast_y=32'(last_y)+1;end
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
    logic [5:0] range_i_flags;

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
    add_equal #(.p_width(p_high_w), .p_use_lut(p_cfg_idle_use_lut)) u_high_next (
      .i_a(high_next_i_a),
      .i_b(high_next_i_b),
      .i_carry_in(high_next_i_carry_in),
      .i_target(high_next_i_target),
      .o_equal(high_next_o_equal)
    );
    // 低位进位和高位关系在单个查找表中合并，组范围直接参与快速接收的末级判断。
    assign range_i_flags = {high_equal, low_within, high_next_o_equal,
                            column_end_low[TILE_COUNT_W], high_before, remaining_wrap};
    if (p_cfg_idle_use_lut) begin : g_range_lut
      LUT6 #(.INIT(64'hefef_aeee_eeee_aeee)) u_range (
        .I0(range_i_flags[0]), .I1(range_i_flags[1]), .I2(range_i_flags[2]),
        .I3(range_i_flags[3]), .I4(range_i_flags[4]), .I5(range_i_flags[5]),
        .O(incoming_group_fits)
      );
    end else begin : g_range_logic
      assign incoming_group_fits = remaining_wrap ||
        (high_before && (!column_end_low[TILE_COUNT_W] || !high_next_o_equal || low_within)) ||
        (high_equal && !column_end_low[TILE_COUNT_W] && low_within);
    end
  end else begin : g_incoming_group_range_wide
    assign incoming_group_fits = 32'(cols_q) <= 32'(c.group_c) - ch0;
  end

  assign incoming_tap_wrap = incoming_tap_wrap_q;

  // 五位位置同时查出除三的商和余数，组内通道直接保留高位位置。
  localparam bit p_q_decode_use_lut =
`ifdef ASIC_SYNTHESIS
    1'b0;
`elsif XILINX_FPGA
    1'b1;
`else
    1'b0;
`endif
  localparam logic [63:0] p_q_quotient_low = 64'hc0fc_0fc0_38e3_8e38;
  localparam logic [63:0] p_q_quotient_high = 64'hff00_0000_00ff_f000;
  localparam logic [63:0] p_q_remainder = 64'h2492_4924_9249_2492;
  logic [4:0] q_decode_i_index;
  logic q_decode_i_one;
  logic [3:0] q_decode_o_quotient;
  logic [1:0] q_decode_o_remainder;

  assign q_decode_i_index = q0[4:0];
  assign q_decode_i_one = 1'b1;
  if (p_q_decode_use_lut) begin : g_q_decode_lut
    LUT6_2 #(.INIT(p_q_quotient_low)) u_quotient_low (
      .I0(q_decode_i_index[0]), .I1(q_decode_i_index[1]),
      .I2(q_decode_i_index[2]), .I3(q_decode_i_index[3]),
      .I4(q_decode_i_index[4]), .I5(q_decode_i_one),
      .O5(q_decode_o_quotient[0]), .O6(q_decode_o_quotient[1])
    );
    LUT6_2 #(.INIT(p_q_quotient_high)) u_quotient_high (
      .I0(q_decode_i_index[0]), .I1(q_decode_i_index[1]),
      .I2(q_decode_i_index[2]), .I3(q_decode_i_index[3]),
      .I4(q_decode_i_index[4]), .I5(q_decode_i_one),
      .O5(q_decode_o_quotient[2]), .O6(q_decode_o_quotient[3])
    );
    LUT6_2 #(.INIT(p_q_remainder)) u_remainder (
      .I0(q_decode_i_index[0]), .I1(q_decode_i_index[1]),
      .I2(q_decode_i_index[2]), .I3(q_decode_i_index[3]),
      .I4(q_decode_i_index[4]), .I5(q_decode_i_one),
      .O5(q_decode_o_remainder[0]), .O6(q_decode_o_remainder[1])
    );
  end else begin : g_q_decode_logic
    assign q_decode_o_quotient[0] = p_q_quotient_low[q_decode_i_index];
    assign q_decode_o_quotient[1] = p_q_quotient_low[{1'b1, q_decode_i_index}];
    assign q_decode_o_quotient[2] = p_q_quotient_high[q_decode_i_index];
    assign q_decode_o_quotient[3] = p_q_quotient_high[{1'b1, q_decode_i_index}];
    assign q_decode_o_remainder[0] = p_q_remainder[q_decode_i_index];
    assign q_decode_o_remainder[1] = p_q_remainder[{1'b1, q_decode_i_index}];
  end
  assign current_q_div3 = {1'b0, q_decode_o_quotient};
  assign current_q_remainder = {q0[15:5], 3'b000, q_decode_o_remainder};

  // 描述符字段分别比较，快速接收资格在末级合并。
  if (p_cfg_idle_use_lut) begin : g_incoming_compare_lut
    logic [2:0][32:0] compare_i_a, compare_i_b;
    logic [2:0][10:0] part_equal;
    logic [2:0][1:0] group_equal;
    logic [5:0] q_fast_i_groups;
    logic [5:0] carry_i_bits;

    assign compare_i_a[0] = {1'b0, tile_p0};
    assign compare_i_a[1] = {1'b0, tile_q0};
    assign compare_i_a[2] = {1'b0, tile_q0};
    assign compare_i_b[0] = {1'b0, p0};
    assign compare_i_b[1] = {1'b0, q0};
    assign compare_i_b[2] = next_group_q;
    for (genvar value = 0; value < 3; value++) begin : g_value
      for (genvar part = 0; part < 11; part++) begin : g_part
        logic [5:0] equal_i_bits;
        assign equal_i_bits = {compare_i_b[value][3*part +: 3], compare_i_a[value][3*part +: 3]};
        LUT6 #(.INIT(64'h8040_2010_0804_0201)) u_equal (
          .I0(equal_i_bits[0]), .I1(equal_i_bits[1]), .I2(equal_i_bits[2]),
          .I3(equal_i_bits[3]), .I4(equal_i_bits[4]), .I5(equal_i_bits[5]),
          .O(part_equal[value][part])
        );
      end
      assign group_equal[value][0] = &part_equal[value][5:0];
      assign group_equal[value][1] = &part_equal[value][10:6];
    end
    assign incoming_position_equal = group_equal[0];
    assign incoming_q_equal = &group_equal[1];
    // 两段位置等值直接参与每位步长选择，等值时输出零，其他位置选择相应字节步长。
    for (genvar bit_index = 0; bit_index < 32; bit_index++) begin : g_delta
      logic [5:0] delta_i_bits;

      assign delta_i_bits = {1'b0, group_equal[1], incoming_tap_wrap,
                            tap_step_bytes[bit_index], tap_wrap_bytes[bit_index]};
      LUT6 #(.INIT(64'h00ac_acac_00ac_acac)) u_delta (
        .I0(delta_i_bits[0]), .I1(delta_i_bits[1]), .I2(delta_i_bits[2]),
        .I3(delta_i_bits[3]), .I4(delta_i_bits[4]), .I5(delta_i_bits[5]),
        .O(incoming_delta[bit_index])
      );
    end
    // 已算出的低两位进位沿用同一选择关系，与各步长位并行进入数据字比较。
    assign carry_i_bits = {1'b0, group_equal[1], incoming_tap_wrap,
                           incoming_step_low_sum[2], incoming_wrap_low_sum[2]};
    LUT6 #(.INIT(64'h00ac_acac_00ac_acac)) u_carry (
      .I0(carry_i_bits[0]), .I1(carry_i_bits[1]), .I2(carry_i_bits[2]),
      .I3(carry_i_bits[3]), .I4(carry_i_bits[4]), .I5(carry_i_bits[5]),
      .O(incoming_word_i_carry_in)
    );
    assign q_fast_i_groups = {2'b00, group_equal[2], group_equal[1]};
    LUT6 #(.INIT(64'hF888_F888_F888_F888)) u_q_fast (
      .I0(q_fast_i_groups[0]), .I1(q_fast_i_groups[1]),
      .I2(q_fast_i_groups[2]), .I3(q_fast_i_groups[3]),
      .I4(q_fast_i_groups[4]), .I5(q_fast_i_groups[5]),
      .O(incoming_q_fast)
    );
  end else begin : g_incoming_compare_logic
    assign incoming_q_equal = tile_q0 == q0;
    assign incoming_delta = incoming_q_equal ? 32'd0 :
      (incoming_tap_wrap ? tap_wrap_bytes : tap_step_bytes);
    assign incoming_word_i_carry_in = !incoming_q_equal &&
      (incoming_tap_wrap ? incoming_wrap_low_sum[2] : incoming_step_low_sum[2]);
    assign incoming_q_fast = incoming_q_equal || {1'b0, tile_q0} == next_group_q;
    assign incoming_position_equal = {2{tile_p0 == p0}};
  end
  // 坐标资格与单行条件提前合并，晚到的组范围保持单级接收选择。
  assign incoming_fast_i_flags[0] = c.windowed && row_base_valid && coordinate_address_valid;
  assign incoming_fast_i_flags[1] = rows_q == TILE_COUNT_W'(1) && tile_rows == RW'(1);
  assign incoming_fast_i_flags[2] = incoming_group_fits;
  assign incoming_fast_i_flags[4:3] = incoming_position_equal;
  assign incoming_fast_i_flags[5] = incoming_q_fast;
  if (CACHE_POLICY == 3 && p_cfg_idle_use_lut) begin : g_incoming_fast_lut
    LUT6 #(.INIT(64'h8000_0000_0000_0000)) u_fast (
      .I0(incoming_fast_i_flags[0]), .I1(incoming_fast_i_flags[1]),
      .I2(incoming_fast_i_flags[2]), .I3(incoming_fast_i_flags[3]),
      .I4(incoming_fast_i_flags[4]), .I5(incoming_fast_i_flags[5]),
      .O(incoming_fast)
    );
  end else begin : g_incoming_fast_logic
    assign incoming_fast = CACHE_POLICY == 3 && (&incoming_fast_i_flags);
  end
  always_comb begin
    incoming_tap=tap0;incoming_ch=ch0;incoming_kx=kx0;incoming_ky=ky0;
    incoming_ix=row_base_ix;incoming_iy=row_base_iy;
    incoming_pixel=row_base_pixel;incoming_addr=row_base_addr;incoming_group_base=row_group_base;
    incoming_padding=incoming_base_padding;
    if (!incoming_q_equal) begin
      incoming_tap=tap0+1;
      if (incoming_tap_wrap) begin
        incoming_kx=0;incoming_ky=ky0+1;
        incoming_ix=incoming_wrap_ix;
        incoming_iy=incoming_wrap_iy;
        incoming_pixel=incoming_pixel_next;
        incoming_addr=row_base_addr+tap_wrap_bytes;incoming_group_base=row_group_base+tap_wrap_bytes;
        incoming_padding=incoming_wrap_padding;
      end else begin
        incoming_kx=kx0+1;
        incoming_ix=incoming_step_ix;
        incoming_pixel=incoming_pixel_next;
        incoming_addr=row_base_addr+tap_step_bytes;incoming_group_base=row_group_base+tap_step_bytes;
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
  // 配置接收与忙状态共用空闲条件，缓存就绪只参与末级组合计算。
  if (p_cfg_idle_use_lut) begin : g_cfg_idle_lut
    logic [2:0][5:0] idle_i_groups;
    logic [2:0] idle_o_groups;
    logic [5:0] idle_i_final;
    logic idle_o_ready;

    // 三个分组直接检查寄存位为零，状态和阶段均采用声明中的二进制取值。
    assign idle_i_groups[0] = {request_pending, state};
    assign idle_i_groups[1] = {cfg_prepare_phase, address_step_phase, prefetch_phase[1:0]};
    assign idle_i_groups[2] = {prefetch_phase[3:2], pred_busy, pred_cfg_busy, pred_cfg_pending, cache_cfg_pending};
    for (genvar idle_group = 0; idle_group < 3; idle_group++) begin : g_group
      LUT6 #(.INIT(64'h0000_0000_0000_0001)) u_idle (
        .I0(idle_i_groups[idle_group][0]), .I1(idle_i_groups[idle_group][1]),
        .I2(idle_i_groups[idle_group][2]), .I3(idle_i_groups[idle_group][3]),
        .I4(idle_i_groups[idle_group][4]), .I5(idle_i_groups[idle_group][5]),
        .O(idle_o_groups[idle_group])
      );
    end
    assign idle_i_final = {1'b1, !cache_hint_pending, cache_cfg_ready, idle_o_groups};
    LUT6 #(.INIT(64'h8000_0000_0000_0000)) u_ready (
      .I0(idle_i_final[0]), .I1(idle_i_final[1]), .I2(idle_i_final[2]),
      .I3(idle_i_final[3]), .I4(idle_i_final[4]), .I5(idle_i_final[5]),
      .O(idle_o_ready)
    );
    assign cfg_ready = idle_o_ready;
  end else begin : g_cfg_idle_logic
    assign cfg_ready = state==IDLE && cfg_prepare_phase==0 && cache_cfg_ready && !pred_busy && !pred_cfg_busy &&
      !cache_cfg_pending && !pred_cfg_pending && !cache_hint_pending &&
      !prefetch_active && !request_pending && address_step_phase==0;
  end
  assign finishing_tile=wr_valid && wr_ready && wr_last;
  // 描述符就绪的静态条件共用，配置有效只参与最终接收选择。
  assign tile_ready_context = (state==IDLE || finishing_tile) && cfg_prepare_phase==0 && configured && !error &&
                              !pred_busy && !pred_cfg_busy && !pred_cfg_pending && !cache_cfg_pending &&
                              !cache_hint_pending && address_step_phase==0;
  assign tile_ready = tile_ready_context && !cfg_valid;
  assign busy = !cfg_ready;
  assign wr_valid = state==STREAM || state==ZERO_STREAM ||
                    (state==WAIT_WORD && cache_rsp_valid && !cache_rsp_error);
  assign wr_slot = slot_q;
  assign wr_row = CW'(row_idx);
  assign wr_col = CW'(col_idx);
  // 行末标志与行号同时保存，当前传输完成只合并列末判断。
  assign {unused_row_index_carry, next_row_idx} = {1'b0, row_idx} + (TILE_COUNT_W+1)'(1);
  assign next_row_last = 32'(next_row_idx) + 32'd1 == 32'(rows_q);
  assign wr_last = row_last_q && chunk_reaches_end;

  assign pred_start = state==ADDRESS && geometry_tile && col_idx==0 &&
    q_current<{1'b0,reduction_len} && ix>=0 && iy>=0 &&
    ix<$signed(COORD_W'(c.input_w)) && iy<$signed(COORD_W'(c.input_h)) &&
    !pred_busy && !cache_hint_pending;
  generate if (SIZE==16 && LINE_BYTES==16 && CACHE_POLICY!=0) begin : g_next_use
    conv_next_use_predictor u_predictor (
      .clk,.rst_n,.cfg_valid(pred_cfg_pending),.cfg(c),
      .cfg_r(predictor_cfg_r),.cfg_groups(groups_q),
      .cfg_eligible(pred_cfg_eligible),.cfg_busy(pred_cfg_busy),.enabled(pred_enabled),.start(pred_start),
      .input_y(32'(iy)),.input_x(32'(ix)),.channel(ch),
      .current_p(p0+32'(row_idx)),.current_q(32'(q_current)),.current_group(group_q),
      .busy(pred_busy),.done(pred_done),.next_rank(pred_rank)
    );
  end else begin : g_no_next_use
    assign pred_cfg_eligible=0;assign pred_cfg_busy=0;assign pred_enabled=0;assign pred_busy=0;
    assign pred_done=0;assign pred_rank=32'hffff_ffff;
  end endgenerate

  assign byte_offset_sum={2'b0,addr[1:0]}+(4'(chunk_count)<<c.input_s16);
  assign word_boundary=byte_offset_sum>=4;
  assign stream_context=state==STREAM || state==WAIT_WORD;
  assign stream_next_request=wr_valid && wr_ready && state!=ZERO_STREAM &&
    TILE_COUNT_W'(chunk_count)<col_remaining && TILE_COUNT_W'(chunk_count)<active_remaining &&
    17'(chunk_count)<group_remaining && word_boundary;
  assign incoming_word_hit = finishing_tile && state == WAIT_WORD ? incoming_live_word_o_equal :
    (word_valid && word_addr[1:0] == 2'd0 && incoming_word_o_equal);
  assign incoming_request=tile_valid && tile_ready && incoming_fast && !incoming_padding &&
    !incoming_word_hit && tile_rows!=0 && 32'(tile_rows)<=SIZE && 32'(tile_cols)<=SIZE &&
    tile_q_before_end && tile_rows_in_range;
  assign cache_req_valid = incoming_request ||
                           (state==FETCH && !(word_valid && word_addr=={addr[31:2],2'b0})) ||
                           stream_next_request;
  assign incoming_context=tile_valid && incoming_fast &&
    (state==IDLE || ((state==WAIT_WORD || state==STREAM || state==ZERO_STREAM) && wr_last));
  assign cache_req_addr=incoming_context ? incoming_addr : stream_context ? next_byte_addr : addr;
  assign cache_rsp_ready = state==WAIT_WORD && (wr_ready || cache_rsp_error);
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
  // The registered request isolates writeback completion and descriptor
  // selection from the cache RAM address and enable inputs.
  assign request_bypass = state==FETCH && !request_pending;
  assign cache_port_valid = request_pending ||
    (request_bypass && !(word_valid && word_addr=={addr[31:2],2'b0}));
  assign cache_req_ready = request_bypass ? cache_port_ready : (!request_pending || cache_port_ready);
  always_comb begin
    current_req_index = pixel_index;
    current_req_epoch = ((32'(c.group_offset)+ch)<<c.input_s16)>>$clog2(LINE_BYTES);
    if (short_pixel_q) begin
      current_req_index = pixel_index>>window_index_shift_q;
      current_req_epoch = 0;
    end
  end
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) request_pending <= 1'b0;
    else if (cache_req_ready) request_pending <= cache_req_valid && !request_bypass;
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
    .CACHE_POLICY(CACHE_POLICY),.BUS_WIDTH(BUS_WIDTH),.DMA_MAX_BYTES(DMA_MAX_BYTES)) u_cache (
    .clk,.rst_n,
    .cfg_valid(cache_config_valid),.cfg_ready(cache_cfg_ready),
    .cfg_base(c.input_base),.cfg_bytes(tensor_bytes),.cfg_bypass(c.bypass_cache),
    .cfg_geometry(pred_cfg_eligible),
    .cfg_windowed(c.windowed),.cfg_prefetch_enable(c.prefetch_enable),
    .req_valid(cache_port_valid),.req_ready(cache_port_ready),
    .req_addr(request_pending ? request_addr_q : addr),
    .req_geometry(request_pending ? request_geometry_q : geometry_tile),
    .req_event_first(request_pending ? request_event_first_q : (geometry_tile && addr[3:0]==0)),
    .hint_valid(line_hint_valid),.hint_next(line_hint_rank),.hint_pending(cache_hint_pending),
    .req_window_index_valid(request_pending ? request_index_valid_q : req_index_valid),
    .req_window_index(request_pending ? request_index_q : current_req_index),
    .req_window_epoch(request_pending ? request_epoch_q : current_req_epoch),
    .req_window_retire(request_retire),
    .req_window_progress(request_pending ? request_progress_q : oy),
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
  if (LANES <= 4) begin : g_group_end_by_lane
    logic [LANES:0] step_o_equal, selected_end;

    // 各种通道数的组末关系提前计算，当前周期只选择最后有效通道。
    for (genvar step = 0; step <= LANES; step++) begin : g_step
      logic [16:0] step_i_b;

      assign step_i_b = 17'(step);
      add_equal #(.p_width(17)) u_step (
        .i_a(group_end_i_a), .i_b(step_i_b), .i_target(group_end_i_target),
        .i_carry_in(group_end_i_carry_in), .o_equal(step_o_equal[step])
      );
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
    add_equal #(.p_width(17), .p_use_lut(p_cfg_idle_use_lut)) u_group_end (
      .i_a(group_end_i_a), .i_b(group_end_i_b), .i_target(group_end_i_target),
      .i_carry_in(group_end_i_carry_in), .o_equal(group_end_o_equal)
    );
  end

  if (LANES <= 4) begin : g_short_group_lane
    logic [2:0][15:0] cfg_group_last;
    logic cfg_has_channel;
    logic [2:0] cfg_short_group;

    assign cfg_has_channel = cfg.group_c != ch_q;
    for (genvar offset = 0; offset < 3; offset++) begin : g_cfg_offset
      assign cfg_group_last[offset] = cfg.group_c - 16'(offset + 1);
      assign cfg_short_group[offset] = cfg.group_c >= 16'(offset + 1) &&
        ch_q == cfg_group_last[offset];
    end
    for (genvar lane = 0; lane < 4; lane++) begin : g_cfg_lane
      assign group_range_cfg[lane] = cfg_has_channel &&
        (lane < 1 || !cfg_short_group[0]) &&
        (lane < 2 || !cfg_short_group[1]) &&
        (lane < 3 || !cfg_short_group[2]);
    end
    for (genvar source = 0; source < 6; source++) begin : g_source
      logic group_has_channel;
      logic one_channel, two_channels, three_channels;

      if (source == 5) begin : g_advancing_channel
        logic [3:0][15:0] step_i_target;
        logic [3:0] boundary_selected;
        logic [11:0] high_i_a, high_i_b;
        logic [3:0] low_i_a;
        logic low_i_carry_in;
        localparam logic [63:0] p_priority_select = 64'hfedc_3210_fedc_3210;
        localparam logic [63:0] p_priority_select_high = 64'hfedc_3210_0000_0000;

        // 目标低位确定传向高位的进位，高位等式可与各个固定增量并行计算。
        assign high_i_a = ch_q[15:4];
        assign high_i_b = 12'd0;
        assign low_i_a = ch_q[3:0];
        assign low_i_carry_in = 1'b0;
        assign step_i_target = {group_minus_three_q, group_minus_two_q, last_group_channel_q, c.group_c};
        for (genvar boundary = 0; boundary < 4; boundary++) begin : g_boundary
          logic [11:0] high_i_target;
          logic [3:0] low_i_target;
          logic high_i_carry_in, high_o_equal, high_gate;
          logic [LANES:0] step_equal;
          localparam logic [63:0] p_final_select = boundary == 0 ?
              ~p_priority_select_high : p_priority_select_high;
          localparam logic [63:0] p_lower_select = LANES >= 3 ? p_priority_select : p_final_select;

          assign high_i_target = step_i_target[boundary][15:4];
          assign low_i_target = step_i_target[boundary][3:0];
          assign high_i_carry_in = ch_q[3] && !step_i_target[boundary][3];
          add_equal #(.p_width(12)) u_high (
            .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
            .i_carry_in(high_i_carry_in), .o_equal(high_o_equal)
          );
          assign high_gate = high_o_equal && (boundary == 0 || c.group_c >= 16'(boundary));
          for (genvar step = 0; step <= LANES; step++) begin : g_step
            logic [3:0] low_i_b;

            assign low_i_b = 4'(step);
            add_equal #(.p_width(4)) u_low (
              .i_a(low_i_a), .i_b(low_i_b), .i_target(low_i_target),
              .i_carry_in(low_i_carry_in), .o_equal(step_equal[step])
            );
          end
          if (p_cfg_idle_use_lut) begin : g_lut_select
            logic [5:0] lower_i_value;
            logic lower_o_value;

            // 两级优先选择保留任意有效通道掩码，选择控制位于宽比较之后。
            assign lower_i_value[0] = chunk_lane_allowed[0];
            assign lower_i_value[2] = step_equal[0];
            assign lower_i_value[3] = step_equal[1];
            assign lower_i_value[5] = LANES >= 3 ? 1'b0 : high_gate;
            if (LANES >= 2) begin : g_second_lane
              assign lower_i_value[1] = chunk_lane_allowed[1];
              assign lower_i_value[4] = step_equal[2];
            end else begin : g_one_lane
              assign lower_i_value[1] = 1'b0;
              assign lower_i_value[4] = 1'b0;
            end
            LUT6 #(.INIT(p_lower_select)) u_lower (
              .I0(lower_i_value[0]), .I1(lower_i_value[1]), .I2(lower_i_value[2]),
              .I3(lower_i_value[3]), .I4(lower_i_value[4]), .I5(lower_i_value[5]),
              .O(lower_o_value)
            );
            if (LANES >= 3) begin : g_upper_lanes
              logic [5:0] upper_i_value;
              logic upper_o_value;

              assign upper_i_value[0] = chunk_lane_allowed[2];
              assign upper_i_value[2] = lower_o_value;
              assign upper_i_value[3] = step_equal[3];
              assign upper_i_value[5] = high_gate;
              if (LANES == 4) begin : g_fourth_lane
                assign upper_i_value[1] = chunk_lane_allowed[3];
                assign upper_i_value[4] = step_equal[4];
              end else begin : g_three_lanes
                assign upper_i_value[1] = 1'b0;
                assign upper_i_value[4] = 1'b0;
              end
              LUT6 #(.INIT(p_final_select)) u_upper (
                .I0(upper_i_value[0]), .I1(upper_i_value[1]), .I2(upper_i_value[2]),
                .I3(upper_i_value[3]), .I4(upper_i_value[4]), .I5(upper_i_value[5]),
                .O(upper_o_value)
              );
              assign boundary_selected[boundary] = upper_o_value;
            end else begin : g_lower_lanes
              assign boundary_selected[boundary] = lower_o_value;
            end
          end else begin : g_logic_select
            logic low_selected;

            always_comb begin
              low_selected = step_equal[0];
              for (int lane = 0; lane < LANES; lane++) begin
                if (chunk_lane_allowed[lane]) low_selected = step_equal[lane+1];
              end
            end
            assign boundary_selected[boundary] = boundary == 0 ?
                !(high_gate && low_selected) : high_gate && low_selected;
          end
        end
        assign group_has_channel = boundary_selected[0];
        assign one_channel = boundary_selected[1];
        assign two_channels = boundary_selected[2];
        assign three_channels = boundary_selected[3];
      end else begin : g_saved_channel
        assign group_has_channel = c.group_c != group_range_channel[source];
        assign one_channel = c.group_c != 16'd0 && group_range_channel[source] == last_group_channel_q;
        assign two_channels = c.group_c >= 16'd2 && group_range_channel[source] == group_minus_two_q;
        assign three_channels = c.group_c >= 16'd3 && group_range_channel[source] == group_minus_three_q;
      end
      for (genvar lane = 0; lane < 4; lane++) begin : g_lane
        if (source == 5 && p_cfg_idle_use_lut && lane > 0) begin : g_fixed_range
          localparam logic [63:0] p_range_value = lane == 1 ? 64'h2222_2222_2222_2222 :
              lane == 2 ? 64'h0202_0202_0202_0202 : 64'h0002_0002_0002_0002;
          logic [5:0] range_i_value;
          logic range_o_value;

          // 各通道独立合并边界标志，使晚到的通道选择只增加一级范围逻辑。
          assign range_i_value = {2'b00, three_channels, two_channels, one_channel, group_has_channel};
          LUT6 #(.INIT(p_range_value)) u_range (
            .I0(range_i_value[0]), .I1(range_i_value[1]), .I2(range_i_value[2]),
            .I3(range_i_value[3]), .I4(range_i_value[4]), .I5(range_i_value[5]),
            .O(range_o_value)
          );
          assign group_range_next[source][lane] = range_o_value;
        end else begin : g_logic_range
          assign group_range_next[source][lane] = group_has_channel &&
            (lane < 1 || !one_channel) && (lane < 2 || !two_channels) && (lane < 3 || !three_channels);
        end
      end
    end
    // 范围标志与当前通道同时保存，传输结束判断直接读取寄存结果。
    assign group_lane_allowed = group_range_q[LANES-1:0];
  end else if (LANES <= 32768) begin : g_group_lane_range
    assign group_range_cfg = '0;
    assign group_range_next = '0;
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
    for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
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
      assign group_lane_allowed[lane] = remaining_wrap ||
          (high_before_end && (!lane_last_low[p_group_low_w] || !high_before_end_by_one || low_before_end)) ||
          (high_at_end && !lane_last_low[p_group_low_w] && low_before_end);
    end
  end else begin : g_group_lane_range_wide
    assign group_range_cfg = '0;
    assign group_range_next = '0;
    for (genvar lane = 0; lane < LANES; lane++) begin : g_lane
      assign group_lane_allowed[lane] = 17'(lane) < group_remaining;
    end
  end

  // 每条通道直接检查字内偏移，常量边界同时覆盖八位和十六位输入。
  for (genvar lane = 0; lane < LANES; lane++) begin : g_word_lane
    logic allowed_s8, allowed_s16;
    if (lane < 4) begin : g_s8
      assign allowed_s8 = {1'b0, addr[1:0]} < 3'(4-lane);
    end else begin : g_s8_empty
      assign allowed_s8 = 1'b0;
    end
    if (lane < 2) begin : g_s16
      assign allowed_s16 = {1'b0, addr[1:0]} < 3'(3-2*lane);
    end else begin : g_s16_empty
      assign allowed_s16 = 1'b0;
    end
    assign word_lane_allowed[lane] = c.input_s16 ? allowed_s16 : allowed_s8;
    assign chunk_end_lane[lane] = chunk_lane_allowed[lane] &&
      col_remaining == TILE_COUNT_W'(lane+1);
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
    assign corrected_s8_low[data_lane] = {1'b0, selected_s8_byte[data_lane]} + {1'b0, c.input_offset[7:0]};
    assign corrected_s8_high[data_lane] = selected_s8_byte[data_lane][7] ?
      (corrected_s8_low[data_lane][8] ? c.input_offset[15:8] : offset_high_minus_one) :
      (corrected_s8_low[data_lane][8] ? offset_high_plus_one : c.input_offset[15:8]);
    assign corrected_s8_value[data_lane] = {corrected_s8_high[data_lane], corrected_s8_low[data_lane][7:0]};
  end
  assign stream_word = state == WAIT_WORD ? cache_rsp_data : word_buf;

  always_comb begin
    group_remaining={1'b0,c.group_c}-{1'b0,ch_q};
    chunk_count = '0;
    for (int lane=0;lane<LANES;lane++) begin
      chunk_lane_allowed[lane]=TILE_COUNT_W'(lane)<col_remaining &&
        (col_idx>=active_cols_q || (group_lane_allowed[lane] && TILE_COUNT_W'(lane)<active_remaining)) &&
        ((state!=STREAM && state!=WAIT_WORD) || word_lane_allowed[lane]);
      if (chunk_lane_allowed[lane]) chunk_count=CHUNK_COUNT_W'(lane+1);
    end
  end

  // 字内偏移只有四种取值，固定字节选择直接形成当前写入数据。
  always_comb begin
    case (addr[1:0])
      2'd0: selected_word = stream_word;
      2'd1: selected_word = {8'd0, stream_word[31:8]};
      2'd2: selected_word = {16'd0, stream_word[31:16]};
      2'd3: selected_word = {24'd0, stream_word[31:24]};
      default: selected_word = 32'd0;
    endcase
  end

  always_comb begin
    for (int l=0;l<LANES;l++) begin
      wr_mask[l]=32'(l)<chunk_count;
      wr_data[l]=0;
      if ((state==STREAM || state==WAIT_WORD) && 32'(l)<chunk_count) begin
        if (c.input_s16) wr_data[l]=$signed(16'(selected_word>>(l*16)));
        else wr_data[l]=$signed(corrected_s8_value[l]);
      end
    end
  end

  always_comb begin
    cfg_pixel_bytes = 32'(cfg.input_c) << cfg.input_s16;
    cfg_line_pixels = 1;
    for (int n=1; n<=LINE_BYTES; n++)
      if (cfg_pixel_bytes <= 32'((LINE_BYTES-1)/n)) cfg_line_pixels=32'(n)+1;
    cfg_pf_step=cfg.kernel_w==1 ? 32'(cfg.stride_w) : 32'(cfg.dilation_w);
    if (cfg_pf_step<cfg_line_pixels) cfg_pf_step=cfg_line_pixels;
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
      kernel_width_valid_q <= cfg.kernel_w != 16'd0;
    end
  end

  // 当前项与新描述符分别完成索引移位和纪元运算，描述符有效条件只控制末级选择。
  assign {unused_incoming_epoch_carry, incoming_epoch_channel} =
    {17'd0, c.group_offset} + {1'b0, incoming_ch};
  assign incoming_req_index = short_pixel_q ? incoming_pixel >> window_index_shift_q : incoming_pixel;
  assign incoming_req_epoch = short_pixel_q ? 32'd0 :
    (incoming_epoch_channel << c.input_s16) >> $clog2(LINE_BYTES);
  always_comb begin
    request_y=incoming_context ? incoming_iy : iy;
    request_output_y=incoming_context ? p_fast_y : oy;
    req_index_valid=window_index_valid_q;
    req_index=incoming_context ? incoming_req_index : current_req_index;
    req_epoch=incoming_context ? incoming_req_epoch : current_req_epoch;
    pf_step=pf_step_q;
    pf_distance=pf_distance_q;
    pf_x=32'(pfa_x)+pf_step;pf_y=32'(pfa_y);
    if (pf_x>=32'(c.input_w)) begin
      pf_x=0;
      pf_y=32'(pfa_y)+(c.kernel_h==1 ? 32'(c.stride_h) : 32'(c.dilation_h));
    end
    // A single-position channel fragment follows the kernel rows. Keep its
    // lookahead inside the next kernel row before advancing along the image.
    pf_wrap_x=pfa_x+$signed(COORD_W'(pf_fragment_dx_q));
    if (c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
        c.kernel_w>1 && c.kernel_h>1 && c.dilation_w==1 && c.dilation_h==1 &&
        pfa_kernel_x+pf_distance>=32'(c.kernel_w) &&
        pfa_kernel_x+pf_distance<2*32'(c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(pfa_y)+1;
    end
    // Strided windows prefetch the same kernel coordinate in the following
    // two output positions. Word offsets distribute requests across both
    // positions, including the next output row.
    pf_window_ahead=c.windowed && pfa_rows==1 && pfa_cols<=32'(c.group_c) &&
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
    pf_channel=32'(c.group_offset)+pfa_channel;
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
          pfa_x <= ix; pfa_y <= iy;
          pfa_channel <= ch; pfa_origin_channel <= ch0;
          pfa_output_x <= ox; pfa_output_y <= oy;
          pfa_kernel_x <= kx; pfa_rows <= 32'(rows_q); pfa_cols <= 32'(cols_q);
          pfa_ref_addr <= request_pending ? request_addr_q : addr;
          pfa_ref_index <= request_pending ? request_index_q : current_req_index;
          pfa_ref_epoch <= request_pending ? request_epoch_q : current_req_epoch;
          pfa_ref_index_valid <= request_pending ? request_index_valid_q : req_index_valid;
        end
        1: begin
          pf_distance_q <= c.windowed ? 1+(((pfa_channel-pfa_origin_channel)<<c.input_s16)>>2) : 32'd1;
          prefetch_phase <= 2;
        end
        2: begin
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
          pf0_ref_epoch <= pfa_ref_epoch; pf0_ref_retire <= pfa_retire;
          pf0_ref_index_valid <= pfa_ref_index_valid; pf0_fragment <= pf_next_fragment;
          pf0_coordinate_valid <= pf_coordinate_valid;
          prefetch_phase <= 4;
        end
        4: begin
          pf1_pixel <= pf0_y * 32'(c.input_w) + pf0_x;
          pf1_channel <= pf0_channel; pf1_epoch <= pf0_epoch; pf1_retire <= pf_retire;
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
  assign channel_descriptor_valid = tile_rows != RW'(0) && 32'(tile_rows) <= SIZE &&
    32'(tile_cols) <= SIZE && tile_q_before_end && tile_rows_in_range;
  assign channel_accept_i_flags = {1'b1, incoming_fast, channel_descriptor_valid,
                                  tile_ready_context, !cfg_valid, tile_valid};
  if (p_cfg_idle_use_lut) begin : g_channel_accept_lut
    LUT6 #(.INIT(64'h8000_0000_0000_0000)) u_accept (
      .I0(channel_accept_i_flags[0]), .I1(channel_accept_i_flags[1]),
      .I2(channel_accept_i_flags[2]), .I3(channel_accept_i_flags[3]),
      .I4(channel_accept_i_flags[4]), .I5(channel_accept_i_flags[5]),
      .O(channel_accept_fire)
    );
  end else begin : g_channel_accept_logic
    assign channel_accept_fire = &channel_accept_i_flags;
  end
  always_comb begin
    channel_update = ch_q;
    case (state)
      WAIT_WORD, STREAM, ZERO_STREAM: begin
        if (!(state == WAIT_WORD && cache_rsp_valid && cache_rsp_error) && wr_valid && wr_ready) begin
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
      Q_DECODE: begin
        if (q0 == 32'd0) begin
          channel_update = 16'd0;
        end else if (group_shape_o_valid) begin
          channel_update = 16'(q0 & (32'(c.group_c) - 32'd1));
        end else if (c.group_c == 16'd3 && q0 < 32'd27) begin
          channel_update = current_q_remainder;
        end
      end
      Q_WAIT: begin
        if (decode_index == q0) begin
          channel_update = 16'(decode_inner);
        end
      end
      default: ;
    endcase
  end
  // 相邻两位共用接收选择，配置和描述符有效只经过一个最终数据选择表。
  if (p_cfg_idle_use_lut) begin : g_channel_mux_lut
    logic channel_mux_i_one;
    assign channel_mux_i_one = 1'b1;
    for (genvar pair = 0; pair < 8; pair++) begin : g_pair
      logic [4:0] mux_i_bits;
      assign mux_i_bits = {channel_accept_fire, incoming_ch[2*pair+1], channel_update[2*pair+1],
                          incoming_ch[2*pair], channel_update[2*pair]};
      LUT6_2 #(.INIT(64'hff00_f0f0_cccc_aaaa)) u_mux (
        .I0(mux_i_bits[0]), .I1(mux_i_bits[1]), .I2(mux_i_bits[2]),
        .I3(mux_i_bits[3]), .I4(mux_i_bits[4]), .I5(channel_mux_i_one),
        .O5(channel_value[2*pair]), .O6(channel_value[2*pair+1])
      );
    end
  end else begin : g_channel_mux_logic
    assign channel_value = channel_accept_fire ? 16'(incoming_ch) : channel_update;
  end
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
      ox_q <= 16'(0); oy_q <= 16'(0); ky_q <= 16'(0); kx_q <= 16'(0); ky0_q <= 16'(0); kx0_q <= 16'(0); ch0_q <= 16'(0);
      group_range_q <= 4'b0000;
      tap_group_base<=0;row_group_base<=0;
      q_current<=0; ix <= COORD_W'(0); iy <= COORD_W'(0); pixel_index <= 32'(0); pad_q<=0; addr<=0;
      word_buf<=0; word_addr<=0; word_valid<=0; slot_q<=0;
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
      if (state==WAIT_WORD && wr_valid && wr_ready) begin
        word_buf<=cache_rsp_data;word_addr<={addr[31:2],2'b0};word_valid<=1;
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
        group_range_q <= group_range_cfg;
        next_group_q <= {1'b0, q0} + 33'(cfg.group_c);
        word_valid<=0; reduction_len<=0;
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
      end else if (tile_valid && tile_ready) begin
          if (tile_rows==0 || 32'(tile_rows)>SIZE || 32'(tile_cols)>SIZE || !tile_q_before_end ||
              !tile_rows_in_range) begin
            tile_error<=1; error<=1; state<=IDLE;
          end else begin
            p0<=tile_p0; q0<=tile_q0; q_current<={1'b0,tile_q0};
            next_group_q <= {1'b0, tile_q0} + 33'(c.group_c);
            row_last_q <= TILE_COUNT_W'(tile_rows) == TILE_COUNT_W'(1);
            rows_q<=TILE_COUNT_W'(tile_rows); cols_q <= (tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
            // 接收描述符时保存剩余列数，后续写入直接消费该计数。
            col_remaining <= (tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
            if (reduction_len-tile_q0<32'(tile_cols==0 ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols))) begin
              active_cols_q <= TILE_COUNT_W'(reduction_len-tile_q0);
              active_remaining <= TILE_COUNT_W'(reduction_len-tile_q0);
            end else begin
              active_cols_q <= (tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
              active_remaining <= (tile_cols==0) ? TILE_COUNT_W'(SIZE) : TILE_COUNT_W'(tile_cols);
            end
            row_idx<=0; col_idx<=0; slot_q<=tile_slot;
            group_q<=tile_group;
            row_base_valid<=0;coordinate_address_valid<=0;row_coordinate_valid<=0;current_coordinate_valid<=0;
            // Windowed requests carry spatial retirement metadata directly.
            geometry_tile<=pred_enabled && (CACHE_POLICY!=3 || !c.windowed) &&
                           (tile_cols==0 || 32'(tile_cols)==SIZE) && tile_p0[3:0]==0 && tile_q0[3:0]==0 &&
                           tile_group<groups_q;
            if(incoming_fast) begin
              tap0<=incoming_tap;ch0_q <= 16'(incoming_ch);
              group_range_q <= group_range_next[1];
              ky_q <= 16'(incoming_ky);
              ky0_q <= 16'(incoming_ky);
              kx_q <= 16'(incoming_kx);
              tap_wrap_q <= kernel_width_valid_q && (16'(incoming_kx) == last_kernel_col_q);
              kx0_q <= 16'(incoming_kx);
              incoming_tap_wrap_q <= kernel_width_valid_q && (16'(incoming_kx) == last_kernel_col_q);
              ix <= COORD_W'(incoming_ix);iy <= COORD_W'(incoming_iy);pixel_index <= 32'(incoming_pixel);
              addr<=incoming_addr;pad_q<=incoming_padding;
              tap_group_base<=incoming_group_base;row_group_base<=incoming_group_base;
              row_base_valid<=1;coordinate_address_valid<=1;row_coordinate_valid<=1;current_coordinate_valid<=1;
              row_base_ix <= COORD_W'(incoming_ix);row_base_iy <= COORD_W'(incoming_iy);
              row_base_pixel <= 32'(incoming_pixel);row_base_addr<=incoming_addr;
              if (incoming_padding) state<=ZERO_STREAM;
              else if (incoming_word_hit) state<=STREAM;
              else state<=cache_req_ready ? WAIT_WORD : FETCH;
            end else state<=P_DECODE;
          end
      end else case (state)
        WAIT_WORD, STREAM, ZERO_STREAM: begin
          if (state==WAIT_WORD && cache_rsp_valid && cache_rsp_error) begin
            error<=1;tile_error<=1;state<=IDLE;
          end else if (wr_valid && wr_ready) begin
          if (chunk_reaches_end) begin
            if (row_last_q) begin tile_done<=1; state<=IDLE; end
            else begin
              row_idx<=next_row_idx; row_last_q<=next_row_last; col_idx<=0; q_current<={1'b0,q0};
              col_remaining <= cols_q;
              active_remaining <= active_cols_q;
              ky_q <= 16'(ky0); kx_q <= 16'(kx0); tap_wrap_q <= kernel_width_valid_q && (16'(kx0) == last_kernel_col_q);
              group_range_q <= group_range_next[1];
              if (row_wrap) begin ox_q <= 16'(0); row_wrap_q <= c.output_w != 16'd0 && (16'(0) == last_output_col_q); oy_q <= 16'(oy+1); end
              else begin
                ox_q <= 16'(ox+1);
                row_wrap_q <= c.output_w != 16'd0 && row_next_o_equal;
              end
              if (row_base_valid && !geometry_tile) begin
                ix <= COORD_W'(next_row_ix);iy <= COORD_W'(next_row_iy);pixel_index <= 32'(next_row_pixel);
                addr<=next_row_addr;pad_q<=next_row_padding;coordinate_address_valid<=1;
                tap_group_base<=next_row_group_base;row_group_base<=next_row_group_base;
                row_base_ix <= COORD_W'(next_row_ix);row_base_iy <= COORD_W'(next_row_iy);
                row_base_pixel <= 32'(next_row_pixel);row_base_addr<=next_row_addr;
                state<=next_row_padding ? ZERO_STREAM : FETCH;
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
            if (col_idx>=active_cols_q || TILE_COUNT_W'(chunk_count)>=active_remaining) state<=ZERO_STREAM;
            else if (group_end_o_equal) begin

              group_range_q <= group_range_next[0];
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
                addr<=next_tap_addr;pad_q<=next_tap_padding;tap_group_base<=next_tap_addr;
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
                  ix <= COORD_W'(ix+1);pixel_index <= 32'(pixel_index+1);addr<=next_byte_addr;
                  if (!word_boundary) state<=STREAM;
                else if (stream_next_request && cache_req_ready) state<=WAIT_WORD;
                else state<=FETCH;
                end else state<=COORD;
              end
            end else begin

              group_range_q <= group_range_next[5];
              if (pad_q) begin addr<=next_byte_addr;state<=ZERO_STREAM;end
              else begin
                addr<=next_byte_addr;
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
      case (state)
        P_DECODE: if (p_fast_valid) begin
          oy_q <= 16'(p_fast_y);ox_q <= 16'(p_fast_x); row_wrap_q <= p_fast_wrap;state<=Q_DECODE;
          last_p_valid<=1;last_p<=p0;last_p_limit<=p0+32'(c.output_w);last_y<=16'(p_fast_y);last_x<=16'(p_fast_x);
          p_cache_valid[p_cache_select]<=1;p_cache_key[p_cache_select]<=p0;
          p_cache_y[p_cache_select]<=16'(p_fast_y);p_cache_x[p_cache_select]<=16'(p_fast_x);
        end else state<=P_START;
        P_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=P_WAIT;end
        P_WAIT: if (decode_index==p0) begin
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
        Q_DECODE: begin
          if (q0==0) begin
            tap0<=0;ch0_q <= 16'(0);state<=K_DECODE;
            group_range_q <= group_range_next[0];
          end
          else if (group_shape_o_valid) begin
            tap0<=q0>>power_shift(32'(c.group_c));
            ch0_q <= 16'(q0&(32'(c.group_c)-1));state<=K_DECODE;
            group_range_q <= group_range_next[2];
          end else if (c.group_c==3 && q0<27) begin
            tap0<=32'(current_q_div3);

            ch0_q <= current_q_remainder;
            group_range_q <= group_range_next[3];
            state<=K_DECODE;
          end else state<=Q_START;
        end
        Q_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=Q_WAIT;end
        Q_WAIT: if (decode_index==q0) begin
          tap0<=decode_outer; ch0_q <= 16'(decode_inner); state<=K_DECODE;
          group_range_q <= group_range_next[4];
        end
        else begin
          decode_index<=decode_index+1;
          if (decode_end_o_equal[1]) begin decode_inner<=0;decode_outer<=decode_outer+1;end
          else decode_inner<=decode_inner+1;
        end
        K_DECODE: begin
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
        K_START: begin decode_index<=0;decode_outer<=0;decode_inner<=0;state<=K_WAIT;end
        K_WAIT: if (decode_index==tap0) begin
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
        COORD: begin
          coordinate_address_valid<=0;current_coordinate_valid<=0;
          coord_out_x<=32'(ox_q)*32'(c.stride_w);
          coord_out_y<=32'(oy_q)*32'(c.stride_h);
          coord_kernel_x<=32'(kx_q)*32'(c.dilation_w);
          coord_kernel_y<=32'(ky_q)*32'(c.dilation_h);
          state<=COORD_SUM;
        end
        COORD_SUM: begin
          coord_sum_x<={1'b0,coord_out_x}+{1'b0,coord_kernel_x};
          coord_sum_y<={1'b0,coord_out_y}+{1'b0,coord_kernel_y};
          state<=COORD_PAD;
        end
        COORD_PAD: begin
          current_coordinate_valid<=1;
          ix<=$signed(COORD_W'(coord_sum_x))-$signed(COORD_W'(c.pad_left));
          iy<=$signed(COORD_W'(coord_sum_y))-$signed(COORD_W'(c.pad_top));
          state<=ADDRESS;
        end
        ADDRESS: begin
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
        ADDRESS_PIXEL: begin
          pixel_index<=pixel_product+32'(ix);
          state<=ADDRESS_PRODUCT;
        end
        ADDRESS_PRODUCT: begin
          channel_product<=pixel_index*32'(c.input_c);
          state<=ADDRESS_BASE;
        end
        ADDRESS_BASE: begin
          group_base_addr<=c.input_base+((channel_product+32'(c.group_offset))<<c.input_s16);
          state<=ADDRESS_CHANNEL;
        end
        ADDRESS_CHANNEL: begin
          addr<=channel_addr;
          tap_group_base<=group_base_addr;
          coordinate_address_valid<=1;
          if (col_idx==0) begin
            row_base_valid<=1;row_base_ix<=ix;row_base_iy<=iy;row_base_pixel<=pixel_index;
            row_base_addr<=channel_addr;
            row_group_base<=group_base_addr;
          end
          state<=FETCH;
        end
        FETCH: begin
          if (word_valid && word_addr=={addr[31:2],2'b0}) state<=STREAM;
          else if (cache_req_ready) state<=WAIT_WORD;
        end
        IDLE, WAIT_WORD, STREAM, ZERO_STREAM: ;
        default: begin state<=IDLE; configured<=0; error<=1; end
      endcase
    end
  end
`ifdef NPU_SIM_ASSERT
  initial begin
    if (SIZE<2 || (SIZE & (SIZE-1))!=0) $fatal(1,"SIZE must be a power of two >=2");
    if (LANES<1 || LANES>4) $fatal(1,"LANES must be in [1,4]");
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
