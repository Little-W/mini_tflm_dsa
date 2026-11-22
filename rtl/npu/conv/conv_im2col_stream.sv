// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 流式输出的通道范围、地址更新与写入数据选择。
module conv_im2col_stream #(
  parameter int p_size=16,
  parameter int p_slot_w=3,
  parameter int p_lanes=2,
  parameter int p_line_bytes=16,
  parameter int p_bus_width=32,
  parameter int p_narrow_lanes=p_bus_width/8,
  parameter bit p_register_cache_request=1'b1,
  parameter bit p_register_descriptor=1'b1,
  parameter bit p_register_row_address=p_register_descriptor,
  parameter int p_rw=$clog2(p_size+1),
  localparam int p_lane_bytes=p_lanes <= 4 ? 4 : (1 << $clog2(p_lanes)),
  localparam int p_cache_read_bytes=p_lane_bytes < p_line_bytes ? p_lane_bytes : p_line_bytes,
  localparam int p_cache_read_width=8 * p_cache_read_bytes,
  localparam int p_word_shift=$clog2(p_cache_read_bytes),
  localparam bit p_saved_word_range=p_lanes <= 8 && p_lanes <= p_cache_read_bytes,
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_chunk_count_w=$clog2(p_lanes+1),
  localparam int p_group_low_w=p_lanes > 1 && p_lanes <= 32768 ? $clog2(p_lanes) : 1,
  localparam int p_group_high_w=16 - p_group_low_w,
  localparam int p_saved_group_lanes=p_lanes > 4 && p_lanes <= 8 ? 8 : 4,
  localparam int p_coord_w=35,
  localparam logic signed [p_coord_w-1:0] p_coord_max={1'b0,{(p_coord_w-1){1'b1}}},
  localparam bit p_contiguous_chunk=p_lanes <= 8 && p_lanes <= (1 << p_tile_count_w),
  localparam int p_prepared_tile_width=560+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input logic i_clk,
  input logic i_rst_n,
  input logic i_cfg_valid,
  input logic i_cfg_ready,
  input conv_im2col_pkg::conv_cfg_t i_cfg,
  input logic i_tile_valid,
  input logic i_tile_ready,
  input logic [p_rw-1:0] i_tile_rows,
  input logic [p_rw-1:0] i_tile_cols,
  input logic i_wr_valid,
  input logic i_wr_ready,
  input logic i_wr_last,
  input conv_im2col_frontend_pkg::st_t i_state,
  input logic i_word_output_q,
  input conv_im2col_pkg::conv_cfg_t i_c,
  input logic i_tile_rows_in_range,
  input logic i_tile_q_before_end,
  input logic [15:0] i_last_group_channel_q,
  input logic [16:0] i_window_group_remaining_q,
  input logic [31:0] i_q0,
  input logic [p_tile_count_w-1:0] i_col_idx,
  input logic [p_tile_count_w-1:0] i_cols_q,
  input logic [p_tile_count_w-1:0] i_active_cols_q,
  input logic i_row_last_q,
  input logic i_past_active_q,
  input logic i_narrow_output,
  input logic [15:0] i_ch0_q,
  input logic [31:0] i_ch0,
  input logic [32:0] i_q_current,
  input logic signed [p_coord_w-1:0] i_ix,
  input logic [31:0] i_pixel_index,
  input logic [31:0] i_channel_addr,
  input logic i_pad_q,
  input logic [p_cache_read_width-1:0] i_word_buf,
  input logic [31:0] i_word_addr,
  input logic i_word_valid,
  input logic [31:0] i_decode_index,
  input logic [31:0] i_decode_inner,
  input logic i_cache_req_ready,
  input logic i_cache_rsp_valid,
  input logic i_cache_rsp_error,
  input logic [p_word_shift+1:0] i_byte_offset_sum,
  input logic i_descriptor_response_forward,
  input logic i_incoming_next_tile_fast,
  input logic i_incoming_next_position_fast,
  input logic i_incoming_skip_tap,
  input logic [15:0] i_window_next_ch,
  input logic [15:0] i_last_input_col_q,
  input logic [p_cache_read_width-1:0] i_cache_rsp_data,
  input logic i_pred_cfg_busy,
  input logic i_cache_cfg_pending,
  input logic i_pred_cfg_pending,
  input logic i_geometry_tile,
  input logic i_incoming_fast,
  input logic i_incoming_padding,
  input logic [31:0] i_incoming_addr,
  input logic [15:0] i_current_q_remainder,
  input logic i_next_word_o_equal,
  input logic i_incoming_word_o_equal,
  input logic i_incoming_live_word_o_equal,
  input logic i_row_base_valid,
  input logic i_coordinate_address_valid,
  input logic i_row_coordinate_valid,
  input logic i_current_coordinate_valid,
  input logic i_tap_wrap,
  input logic i_next_row_padding,
  input logic i_next_tap_padding,
  input logic i_incoming_tap_wrap_q,
  input logic [31:0] i_next_row_addr,
  input logic [31:0] i_next_tap_addr,
  input logic i_channel_accept_fire,
  input logic [p_prepared_tile_width-1:0] i_committing_tile_packed,
  input logic i_tile_commit,
  input logic i_committing_saved_word_hit,
  input logic i_committing_live_word_hit,
  input logic [1:0] i_next_row_word_match,
  input logic [1:0] i_incoming_advanced_word_match,
  input logic i_group_shape_o_valid,
  input logic i_linear_channel_layout_q,
  output logic signed [15:0] o_wr_data [p_lanes],
  output logic [p_lanes-1:0] o_wr_mask,
  output logic [5:0][15:0] o_group_range_channel,
  output logic [16:0] o_initial_group_remaining,
  output logic [5:0][p_saved_group_lanes:0] o_group_range_next,
  output logic [32:0] o_cfg_next_group,
  output logic [32:0] o_cfg_skip_group,
  output logic [p_lanes-1:0] o_chunk_lane_allowed,
  output logic o_chunk_reaches_end,
  output logic [15:0] o_ch_q,
  output logic o_ix_step_below_limit,
  output logic [p_coord_w-1:0] o_ix_increment,
  output logic [31:0] o_addr,
  output logic o_current_word_hit,
  output logic [p_chunk_count_w-1:0] o_chunk_count,
  output logic o_cache_req_valid,
  output logic o_cache_rsp_ready,
  output logic o_stream_next_request,
  output logic o_next_row_request,
  output logic o_active_after_chunk,
  output logic o_incoming_context,
  output logic o_incoming_word_hit,
  output logic [1:0] o_incoming_tile_group_fits,
  output logic [31:0] o_cache_req_addr,
  output logic o_cache_config_valid,
  output logic o_incoming_tap_wrap,
  output logic [32:0] o_next_q_current,
  output logic [31:0] o_pixel_increment,
  output logic o_group_end_o_equal,
  output conv_im2col_frontend_pkg::st_t o_stream_advance_state
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  typedef struct packed {
    logic invalid, fast, padding, word_hit, output_position_update, output_wrap, kernel_last;
    logic geometry, narrow_output;
    logic [31:0] position, reduction, group_index;
    logic [p_tile_count_w-1:0] rows, columns, active_columns;
    logic [p_slot_w-1:0] slot;
    logic [32:0] next_group, skip_group;
    logic [31:0] tap, channel, kernel_x, kernel_y;
    logic signed [p_coord_w-1:0] input_x, input_y;
    logic [31:0] pixel, address, group_address;
    logic [15:0] output_x, output_y;
    logic [p_saved_group_lanes:0] channel_range;
    logic [8:0] padding_select, padding_value;
    logic [31-p_word_shift:0] word_address;
    logic saved_word_valid;
    logic [9:0] operation;
    logic row_wrap;
  } prepared_tile_t;
  logic [p_cache_read_bytes-1:0] word_available_q;
  logic [p_lanes-1:0] group_lane_allowed;
  logic [p_saved_group_lanes:0] group_range_q;
  logic [p_saved_group_lanes:0] group_range_cfg;
  logic [p_saved_group_lanes:0] group_transfer_range;
  logic group_after_chunk;
  logic [16:0] cfg_next_group_low;
  logic [16:0] cfg_next_group_high;
  logic unused_cfg_skip_carry;
  logic [p_tile_count_w-1:0] col_remaining;
  logic [p_tile_count_w-1:0] active_remaining;
  logic [p_lanes:0] active_lane_allowed_q;
  logic [p_lanes:0] active_lane_update;
  logic [p_lanes:0] column_lane_allowed_q;
  logic [p_lanes:0] column_lane_update;
  logic [2:0][p_tile_count_w-1:0] column_update_candidate;
  logic [p_tile_count_w-1:0] column_update_value;
  logic [2:0] active_update_select;
  logic active_select_commit;
  logic [2:0] active_data_select;
  logic [2:0][p_tile_count_w-1:0] active_update_candidate;
  logic [p_tile_count_w-1:0] active_update_value;
  logic [16:0] group_remaining;
  logic [p_lanes-1:0] word_lane_allowed;
  logic [p_lanes-1:0] lane_context_allowed;
  logic [p_lanes-1:0] word_lane_s8;
  logic [p_lanes-1:0] word_lane_s16;
  logic [p_lanes-1:0] chunk_end_s8;
  logic [p_lanes-1:0] chunk_end_s16;
  logic [p_lanes-1:0] chunk_padding_end_s8;
  logic [p_lanes-1:0] chunk_padding_end_s16;
  logic [p_lanes-1:0] chunk_data_allowed;
  logic unused_ix_increment_carry;
  logic [4:0] address_update_select;
  logic [31:0] address_update_value;
  logic address_stream_write;
  logic address_column_advance;
  logic address_linear_tap;
  logic addr_word_hit_q;
  logic next_tap_saved_hit;
  logic next_byte_saved_hit;
  logic channel_saved_hit;
  logic stream_context;
  logic next_row_word_hit;
  logic [31:0] stream_request_addr;
  logic unused_stream_request_carry;
  (* keep = 1 *) logic column_after_chunk;
  (* keep = 1 *) logic word_boundary;
  logic [p_lanes:0] chunk_selected;
  logic [p_lanes:0] step_word_boundary;
  logic [p_lanes:0] step_saved_hit;
  logic incoming_request;
  logic [p_cache_read_width-1:0] selected_word;
  logic [p_cache_read_width-1:0] stream_word;
  logic [p_lanes-1:0][7:0] selected_s8_byte;
  logic [p_lanes-1:0][8:0] corrected_s8_sum;
  logic [p_lanes-1:0][15:0] corrected_s8_value;
  logic [31:0] next_byte_addr;
  logic [15:0] next_channel;
  logic [15:0] channel_update;
  logic [15:0] channel_value;
  prepared_tile_t committing_tile;
  logic [4:0] word_hit_update_select;
  logic [4:0] word_hit_candidate;
  logic word_hit_write_enable;
  logic word_hit_write_value;
  logic word_response_write;
  logic [16:0] channel_position_sum;
  logic unused_channel_position_carry;
  logic stream_request_eligible;
  logic row_request_eligible;
  logic channel_word_equal;
  logic unused_pixel_increment_carry;
  logic [p_saved_group_lanes:0] group_range_stream_value;
  logic [p_saved_group_lanes:0] group_range_row_value;
  logic [p_saved_group_lanes:0] group_range_restart_value;
  logic [p_saved_group_lanes:0] group_range_advance_value;
  logic group_range_restart_select;
  logic group_range_advance_select;
  logic range_stream_allowed;
  logic range_decode_write;
  (* keep = 1 *) logic [p_saved_group_lanes:0] range_decode_value;
  logic [3:0] range_update_select;
  logic [p_saved_group_lanes:0] range_update_value;
  st_t stream_static_state;
  logic stream_request_selected;
  logic stream_row_selected;
  assign committing_tile = prepared_tile_t'(i_committing_tile_packed);

  assign chunk_selected[0] = p_contiguous_chunk ? !o_chunk_lane_allowed[0] : !(|o_chunk_lane_allowed);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_chunk_selected
    if (step == p_lanes) begin : g_last
      assign chunk_selected[step] = o_chunk_lane_allowed[step-1];
    end else if (p_contiguous_chunk) begin : g_contiguous
      assign chunk_selected[step] = o_chunk_lane_allowed[step-1] && !o_chunk_lane_allowed[step];
    end else begin : g_lower
      assign chunk_selected[step] = o_chunk_lane_allowed[step-1] && !(|o_chunk_lane_allowed[p_lanes-1:step]);
    end
  end
  if (p_chunk_count_w + 1 < 32) begin : g_byte_address
    localparam int p_step_width = p_chunk_count_w + 1;
    logic [p_step_width:0] address_low;
    logic [31-p_step_width:0] address_high_next;
    logic [32-p_step_width:0] address_high_sum;
    logic unused_address_carry;

    // 块内字节步长仅影响低位，高位加一提前完成。
    if (p_lanes <= 8) begin : g_parallel_byte_step
      (* keep = 1 *) logic [p_lanes:0][p_step_width:0] low_for_step;
      // 固定短步长按位生成和值，常量步长消除无效进位项并保留完整进位。
      function automatic logic [p_step_width:0] add_byte_step(
        input logic [p_step_width-1:0] value,
        input logic [p_step_width:0] amount
      );
        logic carry;
        logic value_bit;
        carry = 1'b0;
        for (int bit_index = 0; bit_index <= p_step_width; bit_index++) begin
          value_bit = bit_index < p_step_width ? value[bit_index] : 1'b0;
          add_byte_step[bit_index] = value_bit ^ amount[bit_index] ^ carry;
          carry = (value_bit & amount[bit_index]) |
              ((value_bit | amount[bit_index]) & carry);
        end
      endfunction
      // 每种传输数量先计算低位地址，通道资格只选择完整候选。
      for (genvar step = 0; step <= p_lanes; step++) begin : g_step
        logic [p_step_width:0] low_s8, low_s16;
        assign low_s8 = add_byte_step(o_addr[p_step_width-1:0], (p_step_width+1)'(step));
        assign low_s16 = add_byte_step(o_addr[p_step_width-1:0], (p_step_width+1)'(2*step));
        assign low_for_step[step] = i_c.input_s16 ? low_s16 : low_s8;
      end
      always_comb begin
        address_low = '0;
        for (int step = 0; step <= p_lanes; step++)
          address_low |= {(p_step_width+1){chunk_selected[step]}} & low_for_step[step];
      end
    end else begin : g_encoded_byte_step
    logic [p_step_width-1:0] byte_step;
    assign byte_step = i_c.input_s16 ? {o_chunk_count, 1'b0} : {1'b0, o_chunk_count};
      assign address_low = {1'b0, o_addr[p_step_width-1:0]} + {1'b0, byte_step};
    end
    assign address_high_sum = {1'b0, o_addr[31:p_step_width]} + (33-p_step_width)'(1);
    assign {unused_address_carry, address_high_next} = address_high_sum;
    assign next_byte_addr = {
      address_low[p_step_width] ? address_high_next : o_addr[31:p_step_width],
      address_low[p_step_width-1:0]};
  end else begin : g_byte_address_wide
    logic unused_address_carry;
    assign {unused_address_carry, next_byte_addr} =
      {1'b0, o_addr} + {1'b0, (32'(o_chunk_count) << i_c.input_s16)};
  end

  if (p_chunk_count_w < 33) begin : g_reduction_position
    logic [p_chunk_count_w:0] position_low;
    logic [32-p_chunk_count_w:0] position_high_next;
    logic [33-p_chunk_count_w:0] position_high_sum;
    logic unused_position_carry;

    // 当前归约位置使用同一短步长，高位加一与低位求和并行。
    assign position_low = {1'b0, i_q_current[p_chunk_count_w-1:0]} + {1'b0, o_chunk_count};
    assign position_high_sum = {1'b0, i_q_current[32:p_chunk_count_w]} + (34-p_chunk_count_w)'(1);
    assign {unused_position_carry, position_high_next} = position_high_sum;
    assign o_next_q_current = {
      position_low[p_chunk_count_w] ? position_high_next : i_q_current[32:p_chunk_count_w],
      position_low[p_chunk_count_w-1:0]};
  end else begin : g_reduction_position_wide
    logic unused_position_carry;
    assign {unused_position_carry, o_next_q_current} = {1'b0, i_q_current} + 34'(o_chunk_count);
  end

  // 通道递增直接描述为定宽加法，综合工具可以选择算术资源。

  assign channel_position_sum = {1'b0, o_ch_q} + 17'(o_chunk_count);
  assign {unused_channel_position_carry, next_channel} = channel_position_sum;

  // 当前组的剩余通道数共用一次扩展减法，窗口上下文保存对应剩余值。
  assign o_initial_group_remaining = {1'b0, i_c.group_c} - {1'b0, i_ch0_q};
  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range
    logic [15:0] first_channel;
    logic [16:0] requested_columns;
    assign first_channel = source == 0 ? i_window_next_ch : i_ch0_q;
    assign requested_columns = i_tile_cols == '0 ? 17'(p_size) : 17'(i_tile_cols);
    if (p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_remaining
      logic [16:0] remaining;
      (* keep = 1 *) logic full_tile_fits, explicit_tile_fits;
      assign remaining = source == 0 ? i_window_group_remaining_q : o_initial_group_remaining;
      // 缺省列数与显式列数分别检查，列数选择只作用于最终范围标志。
      assign full_tile_fits = !remaining[16] && 17'(p_size) <= remaining;
      assign explicit_tile_fits = !remaining[16] && 17'(i_tile_cols) <= remaining;
      assign o_incoming_tile_group_fits[source] = i_tile_cols == '0 ? full_tile_fits : explicit_tile_fits;
    end else if (p_tile_count_w < 16) begin : g_split
      localparam int p_high_w = 16 - p_tile_count_w;
      logic [p_tile_count_w:0] column_end_low;
      logic high_before, high_equal, low_within;
      logic [p_high_w-1:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry, high_o_equal;

      assign column_end_low = {1'b0, first_channel[p_tile_count_w-1:0]} +
        (p_tile_count_w+1)'(requested_columns);
      assign high_i_a = first_channel[15:p_tile_count_w];
      assign high_i_b = '0;
      assign high_i_target = i_c.group_c[15:p_tile_count_w];
      assign high_i_carry = 1'b1;
      assign high_before = high_i_a < high_i_target;
      assign high_equal = high_i_a == high_i_target;
      assign low_within = column_end_low[p_tile_count_w-1:0] <= i_c.group_c[p_tile_count_w-1:0];
      add_equal #(.p_width(p_high_w)) u_high_next (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(high_o_equal)
      );
      assign o_incoming_tile_group_fits[source] =
        (high_before && (!column_end_low[p_tile_count_w] || !high_o_equal || low_within)) ||
        (high_equal && !column_end_low[p_tile_count_w] && low_within);
    end else begin : g_wide
      assign o_incoming_tile_group_fits[source] =
          {1'b0, first_channel} + requested_columns <= {1'b0, i_c.group_c};
    end
  end

  assign o_incoming_tap_wrap = i_incoming_tap_wrap_q;

  if (p_lanes <= 8 && p_lanes <= p_cache_read_bytes) begin : g_short_word_advance
    localparam int p_tag_count = 1 + (2*p_lanes + (1 << p_word_shift) - 1) / (1 << p_word_shift);
    localparam int p_tag_index_width = $clog2(p_tag_count);
    logic [p_lanes-1:0] crossing_s8, crossing_s16;
    logic [p_lanes:0] step_boundary_s8, step_boundary_s16;
    logic [p_tag_count-1:0] shared_word_equal;

    // 全部步长共用相邻字标签的比较，数据格式只选择已经完成的匹配结果。
    for (genvar word_step = 0; word_step < p_tag_count; word_step++) begin : g_tag
      logic [31-p_word_shift:0] match_i_a, match_i_b, match_i_target;
      logic match_i_carry;

      assign match_i_a = o_addr[31:p_word_shift];
      assign match_i_b = (32-p_word_shift)'(word_step);
      assign match_i_target = i_word_addr[31:p_word_shift];
      assign match_i_carry = 1'b0;
      add_equal #(.p_width(32-p_word_shift)) u_match (
        .i_a(match_i_a), .i_b(match_i_b), .i_carry_in(match_i_carry),
        .i_target(match_i_target), .o_equal(shared_word_equal[word_step])
      );
    end
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      logic [p_word_shift+1:0] offset_sum;
      logic saved_word_equal;
      assign offset_sum = {2'b0, o_addr[p_word_shift-1:0]} +
        (i_c.input_s16 ? (p_word_shift+2)'(2*step) : (p_word_shift+2)'(step));
      logic boundary_s8, boundary_s16;
      // 固定步长直接与字内剩余字节比较，边界条件不经过地址求和。
      if (step == 0) begin : g_no_advance
        assign boundary_s8 = 1'b0;
        assign boundary_s16 = 1'b0;
      end else begin : g_positive_advance
        if (step >= p_cache_read_bytes) begin : g_s8_full_word
          assign boundary_s8 = 1'b1;
        end else begin : g_s8_remaining
          assign boundary_s8 = p_saved_word_range ? !word_available_q[step] :
              o_addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-step);
        end
        if (2*step >= p_cache_read_bytes) begin : g_s16_full_word
          assign boundary_s16 = 1'b1;
        end else begin : g_s16_remaining
          assign boundary_s16 = p_saved_word_range ? !word_available_q[2*step] :
              o_addr[p_word_shift-1:0] >= p_word_shift'(p_cache_read_bytes-2*step);
        end
      end
      assign step_boundary_s8[step] = boundary_s8;
      assign step_boundary_s16[step] = boundary_s16;
      assign step_word_boundary[step] = i_c.input_s16 ? boundary_s16 : boundary_s8;
      assign saved_word_equal = shared_word_equal[p_tag_index_width'(offset_sum[p_word_shift+1:p_word_shift])];
      assign step_saved_hit[step] = i_state[$clog2(WAIT_WORD)] ? !step_word_boundary[step] :
        i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && saved_word_equal;
    end
    // 固定步长的跨字条件随通道号递增，任意有效通道越界即可确定跨字。
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_crossing_lane
      assign crossing_s8[lane] = lane_context_allowed[lane] && column_lane_allowed_q[lane] &&
          (!i_word_output_q || word_lane_s8[lane]) && step_boundary_s8[lane+1];
      assign crossing_s16[lane] = lane_context_allowed[lane] && column_lane_allowed_q[lane] &&
          (!i_word_output_q || word_lane_s16[lane]) && step_boundary_s16[lane+1];
    end
    // 两种格式先分别归并字末条件，格式寄存位只参与最终选择。
    assign word_boundary = i_c.input_s16 ? (|crossing_s16) : (|crossing_s8);
    assign next_byte_saved_hit = |(chunk_selected & step_saved_hit);
  end else begin : g_wide_word_advance
    assign word_boundary = i_byte_offset_sum >= (p_word_shift+2)'(p_cache_read_bytes);
    assign next_byte_saved_hit = i_state[$clog2(WAIT_WORD)] ?
      next_byte_addr[31:p_word_shift] == o_addr[31:p_word_shift] :
      i_word_valid && i_word_addr == {next_byte_addr[31:p_word_shift], {p_word_shift{1'b0}}};
    assign step_word_boundary = '0;
    assign step_saved_hit = '0;
  end
  // 连续读取只在耗尽当前缓存字时发起，下一请求地址独立于传输数量编码。
  assign stream_request_addr[p_word_shift-1:0] = '0;
  parallel_prefix_add #(.p_width(32-p_word_shift), .p_group_width(4), .p_preserve_groups(1'b1)) u_stream_request_word (
    .i_a(o_addr[31:p_word_shift]), .i_b((32-p_word_shift)'(1)), .i_carry(1'b0),
    .o_sum(stream_request_addr[31:p_word_shift]), .o_carry(unused_stream_request_carry)
  );
  if (p_tile_count_w >= p_chunk_count_w) begin : g_stream_remaining
    logic [p_lanes-1:0] column_after_lane, active_after_lane;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
      assign column_after_lane[lane] = column_lane_allowed_q[lane+1];
      assign active_after_lane[lane] = active_lane_allowed_q[lane+1];
    end
    assign column_after_chunk = column_lane_allowed_q[0] && (&(~o_chunk_lane_allowed | column_after_lane));
    assign o_active_after_chunk = active_lane_allowed_q[0] && (&(~o_chunk_lane_allowed | active_after_lane));
  end else begin : g_stream_remaining_wide
    assign column_after_chunk = p_tile_count_w'(o_chunk_count) < col_remaining;
    assign o_active_after_chunk = p_tile_count_w'(o_chunk_count) < active_remaining;
  end

  assign stream_context=i_state[$clog2(STREAM)] || i_state[$clog2(WAIT_WORD)];

  // 请求的静态资格提前计算，输出握手仅控制最终请求有效位。
  assign stream_request_eligible = !i_state[$clog2(ZERO_STREAM)] &&
      column_after_chunk && o_active_after_chunk && group_after_chunk && word_boundary;
  assign row_request_eligible = !p_register_row_address && o_chunk_reaches_end && !i_row_last_q &&
      i_row_base_valid && !i_geometry_tile && !i_next_row_padding && !next_row_word_hit;
  assign o_stream_next_request = i_wr_valid && i_wr_ready && stream_request_eligible;
  // 字命中标志与当前地址同时保存，请求有效条件只读取一位状态。
  assign o_current_word_hit = (p_register_cache_request || p_register_descriptor) ? addr_word_hit_q :
    i_word_valid && i_word_addr == {o_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  assign next_tap_saved_hit = i_state[$clog2(WAIT_WORD)] ? i_next_word_o_equal :
    i_word_valid && i_word_addr == {i_next_tap_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  // 通道地址的字命中直接比较加法等式，完整地址和匹配结果并行计算。

  assign channel_word_equal = i_channel_addr[31:p_word_shift] == i_word_addr[31:p_word_shift];
  assign channel_saved_hit = i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && channel_word_equal;
  // 当前行最后一拍被接收时，下一行的地址已经由独立加法器准备完成。
  assign next_row_word_hit = i_state[$clog2(WAIT_WORD)] ? i_next_row_word_match[1] :
      i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_next_row_word_match[0];
  // 分段模式先保存下一行地址，再由 FETCH 发起读取。
  assign o_next_row_request = i_wr_valid && i_wr_ready && row_request_eligible;
  assign o_incoming_word_hit = i_incoming_next_position_fast || i_incoming_next_tile_fast || i_incoming_skip_tap ?
    (i_descriptor_response_forward ? i_incoming_advanced_word_match[1] :
      i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_incoming_advanced_word_match[0]) :
    (i_descriptor_response_forward ? i_incoming_live_word_o_equal :
      (i_word_valid && i_word_addr[p_word_shift-1:0] == '0 && i_incoming_word_o_equal));
  assign incoming_request=!p_register_cache_request && !p_register_descriptor && i_tile_valid && i_tile_ready && i_incoming_fast && !i_incoming_padding &&
    !o_incoming_word_hit && i_tile_rows!=0 && 32'(i_tile_rows)<=p_size && 32'(i_tile_cols)<=p_size &&
    i_tile_q_before_end && i_tile_rows_in_range;
  assign o_cache_req_valid = incoming_request ||
                           (i_state[$clog2(FETCH)] && !(o_current_word_hit)) ||
                           o_stream_next_request || o_next_row_request;
  assign o_incoming_context=!p_register_descriptor && i_tile_valid && i_incoming_fast &&
    (i_state[$clog2(IDLE)] || ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]) && i_wr_last));
  assign o_cache_req_addr=!p_register_cache_request && o_incoming_context ? i_incoming_addr : o_next_row_request ? i_next_row_addr :
      stream_context ? stream_request_addr : o_addr;
  assign o_cache_rsp_ready = i_state[$clog2(WAIT_WORD)] && (i_wr_ready || i_cache_rsp_error);
  assign o_cache_config_valid = i_cache_cfg_pending && !i_pred_cfg_pending && !i_pred_cfg_busy;
  // 递增比较并行处理符号、宽位溢出及低十六位边界。
  assign o_ix_step_below_limit = (i_ix == p_coord_max) ||
      (i_ix[p_coord_w-1] && ((i_c.input_w != 16'd0) || i_ix != -35'sd1)) ||
      ((i_c.input_w != 16'd0) && !(|i_ix[p_coord_w-1:16]) && i_ix[15:0] < i_last_input_col_q);

  // 输入横坐标的完整三十五位增量使用分组进位。
  parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(4), .p_preserve_groups(1'b1)) u_input_x_increment (
    .i_a(i_ix), .i_b(p_coord_w'(1)), .i_carry(1'b0),
    .o_sum(o_ix_increment), .o_carry(unused_ix_increment_carry)
  );

  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_pixel_increment (
    .i_a(i_pixel_index), .i_b(32'd1), .i_carry(1'b0),
    .o_sum(o_pixel_increment), .o_carry(unused_pixel_increment_carry)
  );

  // 各种通道来源并行计算组内范围，接收边沿只选择相应标志。
  assign o_group_range_channel[0] = 16'd0;
  assign o_group_range_channel[1] = i_ch0_q;
  assign o_group_range_channel[2] = i_q0[15:0] & i_last_group_channel_q;
  assign o_group_range_channel[3] = i_current_q_remainder;
  assign o_group_range_channel[4] = 16'(i_decode_inner);
  assign o_group_range_channel[5] = next_channel;

  // 传输到组末的条件直接检查加法等式，保留第十七位的回绕语义。
  if (p_lanes <= 8) begin : g_group_end_by_lane
    logic [p_lanes:0] step_o_equal;
    (* keep = 1 *) logic [p_lanes:0] selected_end;

    // 各种通道数的组末关系提前计算，当前周期只选择最后有效通道。
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      // 范围标志与通道坐标同拍保存，相邻边界的转换直接表示剩余长度。
      if (step == 0) begin : g_zero_remaining
        assign step_o_equal[step] = !group_range_q[0];
      end else begin : g_remaining_boundary
        assign step_o_equal[step] = group_range_q[step-1] && !group_range_q[step];
      end
      assign selected_end[step] = chunk_selected[step] && step_o_equal[step];
    end
    assign o_group_end_o_equal = |selected_end;
  end else begin : g_group_end_wide
    logic [16:0] group_end_i_a, group_end_i_b, group_end_i_target;
    logic group_end_i_carry_in;
  assign group_end_i_a = {1'b0, o_ch_q};
  assign group_end_i_b = 17'(o_chunk_count);
  assign group_end_i_target = {1'b0, i_c.group_c};
  assign group_end_i_carry_in = 1'b0;
    add_equal #(.p_width(17)) u_group_end (
      .i_a(group_end_i_a), .i_b(group_end_i_b), .i_target(group_end_i_target),
      .i_carry_in(group_end_i_carry_in), .o_equal(o_group_end_o_equal)
    );
  end

  if (p_lanes <= 8) begin : g_short_group_lane
    localparam int p_lane_compare_width = $clog2(p_saved_group_lanes+1);
    logic [16:0] configured_remaining;
    logic configured_high_nonzero;

    assign configured_remaining = {1'b0, i_cfg.group_c} - {1'b0, o_ch_q};
    assign configured_high_nonzero = |configured_remaining[16:p_lane_compare_width];
    // 常量通道边界仅比较低位，高位非零条件由全部通道共用。
    for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_cfg_lane
      assign group_range_cfg[lane] = configured_high_nonzero ||
          p_lane_compare_width'(lane) < configured_remaining[p_lane_compare_width-1:0];
    end
    // 配置及译码来源共用完整剩余数量，流式递增提前形成每种步长的范围。
    for (genvar source = 0; source < 6; source++) begin : g_source
      if (source == 5) begin : g_stream_advance
        localparam int p_range_low_w = $clog2(p_lanes+p_saved_group_lanes+1);
        logic [16:0] remaining;
        logic remaining_high_nonzero;
        logic channel_high_last;
        logic [p_lanes:0] channel_wrap;
        logic [p_saved_group_lanes:0][p_lanes:0] selected_range;
        logic [p_saved_group_lanes:0][p_lanes:0] selected_transfer_range;
        logic [p_lanes-1:0] transfer_lane_allowed;
        logic [p_lanes:0] transfer_selected;

        // 输出阶段准备组范围，换行事件重新装入行首对应的有效通道。
        for (genvar lane = 0; lane < p_lanes; lane++) begin : g_transfer_lane
          assign transfer_lane_allowed[lane] = (!i_narrow_output || lane < p_narrow_lanes) &&
              group_range_q[lane] && active_lane_allowed_q[lane] && column_lane_allowed_q[lane] &&
              (!i_word_output_q || word_lane_allowed[lane]);
        end
        assign transfer_selected[0] = p_contiguous_chunk ?
            !transfer_lane_allowed[0] : !(|transfer_lane_allowed);
        for (genvar step = 1; step <= p_lanes; step++) begin : g_transfer_step
          if (step == p_lanes) begin : g_last
            assign transfer_selected[step] = transfer_lane_allowed[step-1];
          end else if (p_contiguous_chunk) begin : g_contiguous
            assign transfer_selected[step] = transfer_lane_allowed[step-1] && !transfer_lane_allowed[step];
          end else begin : g_lower
            assign transfer_selected[step] = transfer_lane_allowed[step-1] &&
                !(|transfer_lane_allowed[p_lanes-1:step]);
          end
        end

        // 剩余数量只依赖当前坐标；传输数量不经过宽位加减运算。
        assign remaining = {1'b0, i_c.group_c} - {1'b0, o_ch_q};
        assign remaining_high_nonzero = |remaining[15:p_range_low_w];
        assign channel_high_last = &o_ch_q[15:p_range_low_w];
        for (genvar step = 0; step <= p_lanes; step++) begin : g_step
          logic remaining_before_step;
          logic reaches_group_end;
          if (step == 0) begin : g_no_wrap
            assign channel_wrap[step] = 1'b0;
            assign remaining_before_step = 1'b0;
            assign reaches_group_end = !group_range_q[0];
          end else begin : g_wrap
            assign reaches_group_end = group_range_q[step-1] && !group_range_q[step];
            assign channel_wrap[step] = channel_high_last &&
                o_ch_q[p_range_low_w-1:0] > p_range_low_w'((1<<p_range_low_w)-step-1);
            assign remaining_before_step = remaining[p_range_low_w-1:0] < p_range_low_w'(step);
          end
          for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
            logic range_allowed;
            // 差值处于 [step, step+lane] 时该通道无效，其余差值均有效。
            // 通道坐标按十六位回绕，差值最高位随同一回绕关系判断。
            assign range_allowed = remaining_high_nonzero ||
                (remaining[16] != channel_wrap[step]) ||
                remaining_before_step ||
                (remaining[p_range_low_w-1:0] > p_range_low_w'(step+lane));
            assign selected_range[lane][step] = chunk_selected[step] && range_allowed;
            // 每个固定步长先选择组切换或组内递增，再由当前传输数量选取。
            assign selected_transfer_range[lane][step] = transfer_selected[step] &&
                (reaches_group_end ? o_group_range_next[0][lane] : range_allowed);
          end
        end
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_select_lane
          assign o_group_range_next[source][lane] = |selected_range[lane];
          assign group_transfer_range[lane] = |selected_transfer_range[lane];
        end
      end else begin : g_direct_range
        if (source == 5) begin : g_direct_transfer
          assign group_transfer_range = '0;
        end
        logic [16:0] remaining;
        logic high_nonzero;
        if (source == 1) begin : g_initial
          assign remaining = o_initial_group_remaining;
        end else begin : g_other
          assign remaining = {1'b0, i_c.group_c} - {1'b0, o_group_range_channel[source]};
        end
        assign high_nonzero = |remaining[16:p_lane_compare_width];
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
          assign o_group_range_next[source][lane] = high_nonzero ||
              p_lane_compare_width'(lane) < remaining[p_lane_compare_width-1:0];
        end
      end
    end
    assign group_lane_allowed = group_range_q[p_lanes-1:0];
    assign group_after_chunk = group_range_q[0] &&
      (&(~o_chunk_lane_allowed | group_range_q[p_lanes:1]));
  end else if (p_lanes <= 32768) begin : g_group_lane_range
    logic [p_group_high_w-1:0] group_high_minus_one_q;
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) group_high_minus_one_q <= '1;
      else if (i_cfg_valid && i_cfg_ready)
        group_high_minus_one_q <= i_cfg.group_c[15:p_group_low_w] - p_group_high_w'(1);
    end
    assign group_transfer_range = '0;
    assign group_range_cfg = '0;
    assign o_group_range_next = '0;
    logic [p_lanes:0] group_range;
    assign group_lane_allowed = group_range[p_lanes-1:0];
    // 常量步数的范围同时计算，通道掩码只参与末级并行归并。
    assign group_after_chunk = group_range[0] && (&(~o_chunk_lane_allowed | group_range[p_lanes:1]));
    logic high_before_end, high_at_end, high_before_end_by_one, remaining_wrap;
    if (p_group_low_w == 2) begin : g_split_high_compare
      // 两段高位关系并行计算，最高一段不相等时直接确定整体顺序。
      assign high_before_end = o_ch_q[15:9] < i_c.group_c[15:9] ||
        (o_ch_q[15:9] == i_c.group_c[15:9] && o_ch_q[8:2] < i_c.group_c[8:2]);
    end else begin : g_general_high_compare
      assign high_before_end = o_ch_q[15:p_group_low_w] < i_c.group_c[15:p_group_low_w];
    end
    assign high_at_end = o_ch_q[15:p_group_low_w] == i_c.group_c[15:p_group_low_w];
    assign high_before_end_by_one = o_ch_q[15:p_group_low_w] == group_high_minus_one_q;
    assign remaining_wrap = (!high_before_end && !high_at_end) ||
        (high_at_end && o_ch_q[p_group_low_w-1:0] > i_c.group_c[p_group_low_w-1:0]);
    for (genvar lane = 0; lane <= p_lanes; lane++) begin : g_lane
      logic [p_group_low_w:0] lane_last_low;
      logic low_before_end;
      if (p_group_low_w == 2) begin : g_two_bit_offset
        // 两位偏移按位生成进位与和值，通道范围检查直接使用三位结果。
        if (lane == 0) begin : g_zero
          assign lane_last_low = {1'b0, o_ch_q[1:0]};
        end else if (lane == 1) begin : g_one
          assign lane_last_low = {(&o_ch_q[1:0]), o_ch_q[1] ^ o_ch_q[0], ~o_ch_q[0]};
        end else if (lane == 2) begin : g_two
          assign lane_last_low = {o_ch_q[1], ~o_ch_q[1], o_ch_q[0]};
        end else begin : g_three
          assign lane_last_low = {(|o_ch_q[1:0]), o_ch_q[1] ^ ~o_ch_q[0], ~o_ch_q[0]};
        end
      end else begin : g_general_offset
        assign lane_last_low = {1'b0, o_ch_q[p_group_low_w-1:0]} + (p_group_low_w+1)'(lane);
      end
      assign low_before_end = lane_last_low[p_group_low_w-1:0] < i_c.group_c[p_group_low_w-1:0];
      assign group_range[lane] = remaining_wrap ||
          (high_before_end && (!lane_last_low[p_group_low_w] || !high_before_end_by_one || low_before_end)) ||
          (high_at_end && !lane_last_low[p_group_low_w] && low_before_end);
    end
  end else begin : g_group_lane_range_wide
    assign group_transfer_range = '0;
    assign group_range_cfg = '0;
    assign o_group_range_next = '0;
    assign group_after_chunk = 17'(o_chunk_count) < group_remaining;
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_lane
      assign group_lane_allowed[lane] = 17'(lane) < group_remaining;
    end
  end

  // 每条通道直接检查字内偏移，常量边界同时覆盖八位和十六位输入。
  for (genvar lane = 0; lane < p_lanes; lane++) begin : g_word_lane
    (* keep = 1 *) logic allowed_s8, allowed_s16;
    // 字内偏移扩展一位后与固定边界比较，覆盖一个完整读取字。
    function automatic logic before_word_end(
      input logic [p_word_shift-1:0] value,
      input logic [p_word_shift:0] limit
    );
      before_word_end = {1'b0, value} < limit;
    endfunction
    if (lane < p_cache_read_bytes) begin : g_s8
      assign allowed_s8 = p_saved_word_range ? word_available_q[lane] :
          before_word_end(o_addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-lane));
    end else begin : g_s8_empty
      assign allowed_s8 = 1'b0;
    end
    if (lane < p_cache_read_bytes/2) begin : g_s16
      assign allowed_s16 = p_saved_word_range ? word_available_q[2*lane+1] :
          before_word_end(o_addr[p_word_shift-1:0], (p_word_shift+1)'(p_cache_read_bytes-1-2*lane));
    end else begin : g_s16_empty
      assign allowed_s16 = 1'b0;
    end
    assign word_lane_s8[lane] = allowed_s8;
    assign word_lane_s16[lane] = allowed_s16;
    assign word_lane_allowed[lane] = i_c.input_s16 ? allowed_s16 : allowed_s8;
    // 列数、组范围与输出宽度先形成公共资格，输入格式单独选择字内通道。
    assign lane_context_allowed[lane] = (!i_narrow_output || lane<p_narrow_lanes) &&
        (i_past_active_q || (group_lane_allowed[lane] && active_lane_allowed_q[lane]));
    assign chunk_data_allowed[lane] = lane_context_allowed[lane] &&
        (!i_word_output_q || word_lane_allowed[lane]);
    if (p_tile_count_w >= p_chunk_count_w) begin : g_complete_column
      // 数据区和补零区分别准备行末资格，有效列结束标志只参与末级合并。
      assign chunk_padding_end_s8[lane] = (!i_narrow_output || lane < p_narrow_lanes) &&
          column_lane_allowed_q[lane] && !column_lane_allowed_q[lane+1] &&
          (!i_word_output_q || allowed_s8);
      assign chunk_padding_end_s16[lane] = (!i_narrow_output || lane < p_narrow_lanes) &&
          column_lane_allowed_q[lane] && !column_lane_allowed_q[lane+1] &&
          (!i_word_output_q || allowed_s16);
      assign chunk_end_s8[lane] = chunk_padding_end_s8[lane] &&
          group_lane_allowed[lane] && active_lane_allowed_q[lane];
      assign chunk_end_s16[lane] = chunk_padding_end_s16[lane] &&
          group_lane_allowed[lane] && active_lane_allowed_q[lane];
    end else begin : g_wrapped_column
      assign chunk_end_s8[lane] = 1'b0;
      assign chunk_end_s16[lane] = 1'b0;
      assign chunk_padding_end_s8[lane] = 1'b0;
      assign chunk_padding_end_s16[lane] = 1'b0;
    end
  end
  if (p_tile_count_w >= p_chunk_count_w) begin : g_direct_chunk_end
    logic end_s8, end_s16;
    // 有效列结束时，补零通道沿用当前字和行宽限制；两种格式提前形成行末条件。
    assign end_s8 = (|chunk_end_s8) || (i_past_active_q && (|chunk_padding_end_s8));
    assign end_s16 = (|chunk_end_s16) || (i_past_active_q && (|chunk_padding_end_s16));
    assign o_chunk_reaches_end = !column_lane_allowed_q[0] ||
        (i_c.input_s16 ? end_s16 : end_s8);
  end else begin : g_narrow_chunk_end
    assign o_chunk_reaches_end = p_tile_count_w'(o_chunk_count) == col_remaining;
  end

  // 八位输入的配置偏移范围为负127至128，完整和值由九位有符号数表示。
  for (genvar data_lane = 0; data_lane < p_lanes; data_lane++) begin : g_signed_byte_offset
    assign selected_s8_byte[data_lane] = 8'(selected_word >> (data_lane * 8));
    assign corrected_s8_sum[data_lane] =
        {selected_s8_byte[data_lane][7], selected_s8_byte[data_lane]} + i_c.input_offset[8:0];
    assign corrected_s8_value[data_lane] =
        {{7{corrected_s8_sum[data_lane][8]}}, corrected_s8_sum[data_lane]};
  end
  assign stream_word = i_state[$clog2(WAIT_WORD)] ? i_cache_rsp_data : i_word_buf;

  always_comb begin
    group_remaining={1'b0,i_c.group_c}-{1'b0,o_ch_q};
    o_chunk_count = '0;
    for (int lane=0;lane<p_lanes;lane++) begin
      // 描述符选择写入宽度；缓存字仍保留完整读取宽度供后续拍使用。
      o_chunk_lane_allowed[lane] = chunk_data_allowed[lane] && column_lane_allowed_q[lane];
      if (o_chunk_lane_allowed[lane]) o_chunk_count=p_chunk_count_w'(lane+1);
    end
  end

  // 字节移位仅选择当前自然地址分组内的有效数据，字尾由通道掩码限制。
  assign selected_word = stream_word >> (8*o_addr[p_word_shift-1:0]);

  // 各项范围均从零号通道连续有效，范围交集直接形成连续输出掩码。
  // 列索引可能发生定宽回绕的参数组合保留逐通道后缀归并。
  for (genvar output_lane = 0; output_lane < p_lanes; output_lane++) begin : g_output_mask
    if (p_contiguous_chunk) begin : g_contiguous
      assign o_wr_mask[output_lane] = o_chunk_lane_allowed[output_lane];
    end else begin : g_general
      assign o_wr_mask[output_lane] = |o_chunk_lane_allowed[p_lanes-1:output_lane];
    end
  end
  always_comb begin
    for (int l=0;l<p_lanes;l++) begin
      o_wr_data[l]=0;
      if ((i_state[$clog2(STREAM)] || i_state[$clog2(WAIT_WORD)]) && o_wr_mask[l]) begin
        if (i_c.input_s16) o_wr_data[l]=$signed(16'(selected_word>>(l*16)));
        else o_wr_data[l]=$signed(corrected_s8_value[l]);
      end
    end
  end

  always_comb begin
    channel_update = o_ch_q;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        if (!(i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) && i_wr_valid && i_wr_ready) begin
          if (o_chunk_reaches_end) begin
            if (!i_row_last_q) begin
              channel_update = 16'(i_ch0);
            end
          end else if (i_col_idx < i_active_cols_q && p_tile_count_w'(o_chunk_count) < active_remaining) begin
            if (o_group_end_o_equal) begin
              channel_update = 16'd0;
            end else begin
              channel_update = next_channel;
            end
          end
        end
      end
      i_state[$clog2(Q_DECODE)]: begin
        if (i_q0 == 32'd0) begin
          channel_update = 16'd0;
        end else if (i_group_shape_o_valid) begin
          channel_update = o_group_range_channel[2];
        end else if (i_c.group_c == 16'd3 && i_q0 < 32'd27) begin
          channel_update = i_current_q_remainder;
        end
      end
      i_state[$clog2(Q_WAIT)]: begin
        if (i_decode_index == i_q0) begin
          channel_update = 16'(i_decode_inner);
        end
      end
      default: ;
    endcase
  end
  // 行切换、组切换和通道递增先选择范围，写入握手只控制最终保存。

  // 组末选择先完成一位条件，各通道范围独立合并三种数据来源。
  assign group_range_restart_select = !o_chunk_reaches_end && o_group_end_o_equal;
  assign group_range_advance_select = !o_chunk_reaches_end && !o_group_end_o_equal;
  assign group_range_row_value = {(p_saved_group_lanes+1){o_chunk_reaches_end}} & o_group_range_next[1];
  assign group_range_restart_value = {(p_saved_group_lanes+1){group_range_restart_select}} & o_group_range_next[0];
  assign group_range_advance_value = {(p_saved_group_lanes+1){group_range_advance_select}} & o_group_range_next[5];
  assign group_range_stream_value = p_lanes <= 8 ?
      (group_range_row_value | ({(p_saved_group_lanes+1){!o_chunk_reaches_end}} & group_transfer_range)) :
      (group_range_row_value | group_range_restart_value | group_range_advance_value);

  // 流式范围的保存资格与三种候选值并行计算，返回有效只控制寄存器写入。

  if (!(p_lanes <= 8)) begin : g_qualified_range_write
  (* keep = 1 *) logic range_write_context;
  logic range_position_allowed;
  // 运行状态与行列位置独立检查，传输状态只作用于最后的保存资格。
  always_comb begin
    range_write_context = 1'b0;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        if (i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) begin
        end else if (i_wr_ready) range_write_context = 1'b1;
      end
      default: ;
    endcase
  end
  always_comb begin
    range_position_allowed = 1'b0;
    if (o_chunk_reaches_end) begin
      if (i_row_last_q) begin
      end else range_position_allowed = 1'b1;
    end else if (i_past_active_q || !o_active_after_chunk) begin
    end else range_position_allowed = 1'b1;
  end
  assign range_stream_allowed = range_write_context && range_position_allowed;
  end else begin : g_stream_range_write
    assign range_stream_allowed = i_wr_ready;
  end
  // 译码选择保持状态优先次序，其数据准备与配置及输出握手独立。
  always_comb begin
    range_decode_write = 1'b0;
    range_decode_value = o_group_range_next[4];
    unique case (1'b1)
      i_state[$clog2(P_DECODE)], i_state[$clog2(P_START)], i_state[$clog2(P_WAIT)]: ;
      i_state[$clog2(Q_DECODE)]: begin
        if (i_q0 == 32'd0) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[0];
        end else if (i_group_shape_o_valid) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[2];
        end else if (i_c.group_c == 16'd3 && i_q0 < 32'd27) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[3];
        end
      end
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: begin
        if (i_decode_index == i_q0) range_decode_write = 1'b1;
      end
      default: ;
    endcase
  end
  // 配置只在空闲状态接收，译码、描述符提交和数据输出分别使用互斥状态。
  // 直接描述符模式保留末拍提交优先次序，寄存模式在后续空闲周期提交。
  assign range_update_select[0] = range_decode_write;
  assign range_update_select[1] = i_cfg_valid && i_cfg_ready;
  assign range_update_select[2] = i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign range_update_select[3] = (p_register_descriptor || !i_tile_commit) &&
      i_wr_valid && range_stream_allowed;
  if (p_lanes <= 8) begin : g_range_data_choice
    // 保存资格只控制时钟使能，流式数据独立选择行首或递增范围。
    // 有效列结束后的范围随输出准备；再次进入有效数据前由行首或描述符装入。
    always_comb begin
      range_update_value = group_range_stream_value;
      unique case (1'b1)
        range_update_select[1]: range_update_value = group_range_cfg;
        range_update_select[2]: range_update_value = committing_tile.channel_range;
        range_update_select[0]: range_update_value = range_decode_value;
        default: ;
      endcase
    end
  end else begin : g_range_qualified_choice
    assign range_update_value =
        ({(p_saved_group_lanes+1){range_update_select[0]}} & range_decode_value) |
        ({(p_saved_group_lanes+1){range_update_select[1]}} & group_range_cfg) |
        ({(p_saved_group_lanes+1){range_update_select[2]}} & committing_tile.channel_range) |
        ({(p_saved_group_lanes+1){range_update_select[3]}} & group_range_stream_value);
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) group_range_q <= '0;
    else if (|range_update_select) group_range_q <= range_update_value;
  end

  // 当前通道和新描述符并行准备，接收事件只选择最终数据。
  assign channel_value = i_channel_accept_fire ? 16'(committing_tile.channel) : channel_update;
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_ch_q <= 16'd0;
    end else begin
      o_ch_q <= channel_value;
    end
  end

  // 配置通道数只作用于低十六位，高位递增与低位求和并行完成。
  assign cfg_next_group_low = {1'b0, i_q0[15:0]} + {1'b0, i_cfg.group_c};
  assign cfg_next_group_high = {1'b0, i_q0[31:16]} + 17'd1;
  assign o_cfg_next_group = {
    cfg_next_group_low[16] ? cfg_next_group_high : {1'b0, i_q0[31:16]},
    cfg_next_group_low[15:0]};
  parallel_prefix_add #(.p_width(33), .p_group_width(4), .p_preserve_groups(1'b1)) u_cfg_skip_group (
    .i_a({1'b0, i_q0}), .i_b({16'd0, i_cfg.group_c, 1'b0}), .i_carry(1'b0),
    .o_sum(o_cfg_skip_group), .o_carry(unused_cfg_skip_carry)
  );

  // 地址更新直接使用对应运行状态；配置接收只发生在空闲状态。
  // 寄存描述符在空闲周期提交，直接模式在末拍接收时优先写入新地址。
  assign address_stream_write = i_wr_valid && i_wr_ready && (p_register_descriptor || !i_tile_commit);
  assign address_column_advance = !o_chunk_reaches_end && !i_past_active_q && o_active_after_chunk;
  assign address_linear_tap = !i_coordinate_address_valid && !i_current_coordinate_valid && !i_tap_wrap &&
    !i_pad_q && i_linear_channel_layout_q &&
    o_ix_step_below_limit;
  assign address_update_select[0] = i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign address_update_select[1] = address_stream_write && o_chunk_reaches_end && !i_row_last_q &&
    i_row_base_valid && !i_geometry_tile;
  assign address_update_select[2] = address_stream_write && address_column_advance &&
    o_group_end_o_equal && i_coordinate_address_valid;
  assign address_update_select[3] = address_stream_write && address_column_advance &&
    (!o_group_end_o_equal || address_linear_tap);
  assign address_update_select[4] = i_state[$clog2(ADDRESS_CHANNEL)];
  assign address_update_value = ({32{address_update_select[0]}} & committing_tile.address) |
    ({32{address_update_select[1]}} & i_next_row_addr) |
    ({32{address_update_select[2]}} & i_next_tap_addr) |
    ({32{address_update_select[3]}} & next_byte_addr) |
    ({32{address_update_select[4]}} & i_channel_addr);
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) o_addr <= 32'd0;
    else if (|address_update_select) o_addr <= address_update_value;
  end

  if (p_saved_word_range) begin : g_saved_word_range
    logic [4:0][p_word_shift-1:0] source_low;
    logic [p_cache_read_bytes-1:0][4:0] source_available;
    logic [p_cache_read_bytes-1:0] next_available;

    // 各地址候选并行计算字内剩余范围，接收地址的边沿同时保存范围位。
    assign source_low[0] = committing_tile.address[p_word_shift-1:0];
    assign source_low[1] = i_next_row_addr[p_word_shift-1:0];
    assign source_low[2] = i_next_tap_addr[p_word_shift-1:0];
    assign source_low[3] = next_byte_addr[p_word_shift-1:0];
    assign source_low[4] = i_channel_addr[p_word_shift-1:0];
    for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_byte
      for (genvar source = 0; source < 5; source++) begin : g_source
        assign source_available[byte_index][source] =
            {1'b0, source_low[source]} < (p_word_shift+1)'(p_cache_read_bytes-byte_index);
      end
      // 地址写入资格保持独立；发生保存时，运行状态直接选择对应字内范围。
      assign next_available[byte_index] = i_tile_commit ? source_available[byte_index][0] :
          i_state[$clog2(ADDRESS_CHANNEL)] ? source_available[byte_index][4] :
          o_chunk_reaches_end ? source_available[byte_index][1] :
          (o_group_end_o_equal && i_coordinate_address_valid) ? source_available[byte_index][2] :
          source_available[byte_index][3];
    end
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) word_available_q <= '1;
      else if (|address_update_select) word_available_q <= next_available;
    end
  end else begin : g_combinational_word_range
    assign word_available_q = '0;
  end

  // 保存字命中标志与地址共用更新事件，比较结果仅经过末端选择。
  assign word_response_write = i_state[$clog2(WAIT_WORD)] && i_wr_valid && i_wr_ready;
  assign word_hit_update_select[0] = p_register_descriptor ? i_state[$clog2(DESCRIPTOR_CHECK)] :
      i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign word_hit_update_select[3:1] = address_update_select[3:1];
  assign word_hit_update_select[4] = i_state[$clog2(ADDRESS_CHANNEL)];
  assign word_hit_candidate = {channel_saved_hit, next_byte_saved_hit,
      next_tap_saved_hit, next_row_word_hit,
      p_register_descriptor ? i_committing_saved_word_hit || i_committing_live_word_hit : committing_tile.word_hit};
  assign word_hit_write_enable = (i_cfg_valid && i_cfg_ready) ||
      (|word_hit_update_select) || word_response_write;
  assign word_hit_write_value = |(word_hit_update_select & word_hit_candidate) ||
      (!(|word_hit_update_select) && word_response_write);
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) addr_word_hit_q <= 1'b0;
    else if (word_hit_write_enable) addr_word_hit_q <= word_hit_write_value;
  end

  // 有效列数量与逐通道范围在同一边沿更新，运行期直接读取范围寄存器。
  // 数据选择使用任务阶段；传输和行末资格只控制寄存器使能。
  assign active_select_commit = p_register_descriptor ? i_state[$clog2(IDLE)] : i_tile_commit;
  assign active_data_select[0] = active_select_commit;
  assign active_data_select[1] = !active_select_commit && o_chunk_reaches_end;
  assign active_data_select[2] = !active_select_commit && !o_chunk_reaches_end;
  assign active_update_select[0] = i_tile_commit && !committing_tile.invalid;
  assign active_update_select[1] = address_stream_write && o_chunk_reaches_end && !i_row_last_q;
  assign active_update_select[2] = address_stream_write && !o_chunk_reaches_end;
  assign active_update_candidate[0] = committing_tile.active_columns;
  assign active_update_candidate[1] = i_active_cols_q;
  assign active_update_candidate[2] = active_remaining - p_tile_count_w'(o_chunk_count);
  assign active_update_value =
      ({p_tile_count_w{active_data_select[0]}} & active_update_candidate[0]) |
      ({p_tile_count_w{active_data_select[1]}} & active_update_candidate[1]) |
      ({p_tile_count_w{active_data_select[2]}} & active_update_candidate[2]);
  assign column_update_candidate[0] = committing_tile.columns;
  assign column_update_candidate[1] = i_cols_q;
  assign column_update_candidate[2] = col_remaining - p_tile_count_w'(o_chunk_count);
  assign column_update_value =
      ({p_tile_count_w{active_data_select[0]}} & column_update_candidate[0]) |
      ({p_tile_count_w{active_data_select[1]}} & column_update_candidate[1]) |
      ({p_tile_count_w{active_data_select[2]}} & column_update_candidate[2]);
  for (genvar lane = 0; lane <= p_lanes; lane++) begin : g_active_lane_update
    logic [2:0] candidate_allowed, column_allowed;
    for (genvar source = 0; source < 3; source++) begin : g_source
      if (source == 2 && p_lanes <= 8) begin : g_step
        logic [p_lanes:0] active_allowed, remaining_allowed;
        // 各种传输长度提前计算范围，末通道选择只参与最后归并。
        for (genvar step = 0; step <= p_lanes; step++) begin : g_length
          logic [p_tile_count_w-1:0] active_count, remaining_count;
          assign active_count = active_remaining - p_tile_count_w'(step);
          assign remaining_count = col_remaining - p_tile_count_w'(step);
          assign active_allowed[step] = p_tile_count_w'(lane) < active_count;
          assign remaining_allowed[step] = p_tile_count_w'(lane) < remaining_count;
        end
        assign candidate_allowed[source] = |(chunk_selected & active_allowed);
        assign column_allowed[source] = |(chunk_selected & remaining_allowed);
      end else begin : g_count
        assign candidate_allowed[source] = p_tile_count_w'(lane) < active_update_candidate[source];
        assign column_allowed[source] = p_tile_count_w'(lane) < column_update_candidate[source];
      end
    end
    assign active_lane_update[lane] = |(active_data_select & candidate_allowed);
    assign column_lane_update[lane] = |(active_data_select & column_allowed);
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) column_lane_allowed_q[lane] <= $unsigned(p_tile_count_w'(lane)) < $unsigned(p_tile_count_w'(p_size));
      else if (|active_update_select) column_lane_allowed_q[lane] <= column_lane_update[lane];
    end
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) col_remaining <= p_tile_count_w'(p_size);
    else if (|active_update_select) col_remaining <= column_update_value;
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      active_remaining <= '0;
      active_lane_allowed_q <= '0;
    end else if (|active_update_select) begin
      active_remaining <= active_update_value;
      active_lane_allowed_q <= active_lane_update;
    end
  end

  // 流状态先选择行、通道及填充目标，请求接收结果只参与末级状态选择。

  always_comb begin
    stream_static_state = FETCH;
    stream_request_selected = 1'b0;
    stream_row_selected = 1'b0;
    if (o_chunk_reaches_end) begin
      if (i_row_last_q) stream_static_state = IDLE;
      else if (i_row_base_valid && !i_geometry_tile) begin
        if (i_next_row_padding) stream_static_state = ZERO_STREAM;
        else if (next_row_word_hit) stream_static_state = STREAM;
        else stream_row_selected = 1'b1;
      end else if (i_row_coordinate_valid) stream_static_state = ADDRESS;
      else stream_static_state = COORD;
    end else if (i_past_active_q || !o_active_after_chunk) begin
      stream_static_state = ZERO_STREAM;
    end else if (o_group_end_o_equal) begin
      if (i_coordinate_address_valid) begin
        if (i_next_tap_padding) stream_static_state = ZERO_STREAM;
        else if (i_next_word_o_equal && !i_pad_q) stream_static_state = STREAM;
      end else if (i_current_coordinate_valid) stream_static_state = ADDRESS;
      else if (i_tap_wrap) stream_static_state = COORD;
      else if (!i_pad_q && i_linear_channel_layout_q && o_ix_step_below_limit) begin
        if (!word_boundary) stream_static_state = STREAM;
        else stream_request_selected = stream_request_eligible;
      end else stream_static_state = COORD;
    end else if (i_pad_q) begin
      stream_static_state = ZERO_STREAM;
    end else if (!word_boundary) begin
      stream_static_state = STREAM;
    end else begin
      stream_request_selected = stream_request_eligible;
    end
  end
  always_comb begin
    o_stream_advance_state = stream_static_state;
    if (stream_request_selected && i_cache_req_ready) o_stream_advance_state = WAIT_WORD;
    if (stream_row_selected)
      o_stream_advance_state = row_request_eligible && i_cache_req_ready ? WAIT_WORD : FETCH;
  end

endmodule

`default_nettype wire
