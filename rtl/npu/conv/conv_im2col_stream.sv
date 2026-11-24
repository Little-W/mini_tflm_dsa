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
  localparam bit p_saved_word_range=p_lanes <= 16 && p_lanes <= p_cache_read_bytes,
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_chunk_count_w=$clog2(p_lanes+1),
  localparam int p_group_low_w=p_lanes > 1 && p_lanes <= 32768 ? $clog2(p_lanes) : 1,
  localparam int p_group_high_w=16 - p_group_low_w,
  localparam int p_saved_group_lanes=p_lanes <= 16 ? p_lane_bytes : 4,
  localparam int p_coord_w=35,
  localparam bit p_contiguous_chunk=p_lanes <= 16 && p_lanes <= (1 << p_tile_count_w),
  localparam int p_prepared_tile_width=528+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input wire logic i_clk,
  input wire logic i_rst_n,
  input wire logic i_cfg_valid,
  input wire logic i_cfg_ready,
  input wire conv_im2col_pkg::conv_cfg_t i_cfg,
  input wire logic i_tile_valid,
  input wire logic i_tile_ready,
  input wire logic i_tile_admission_ready,
  input wire logic [p_rw-1:0] i_tile_rows,
  input wire logic [p_rw-1:0] i_tile_cols,
  input wire logic i_wr_valid,
  input wire logic i_wr_ready,
  input wire logic i_wr_last,
  input wire conv_im2col_frontend_pkg::st_t i_state,
  input wire logic i_word_output_q,
  input wire conv_im2col_pkg::conv_cfg_t i_c,
  input wire logic i_tile_rows_in_range,
  input wire logic i_tile_q_before_end,
  input wire logic [15:0] i_last_group_channel_q,
  input wire logic [16:0] i_window_group_remaining_q,
  input wire logic [31:0] i_q0,
  input wire logic [p_tile_count_w-1:0] i_col_idx,
  input wire logic [p_tile_count_w-1:0] i_cols_q,
  input wire logic [p_tile_count_w-1:0] i_active_cols_q,
  input wire logic i_row_last_q,
  input wire logic i_past_active_q,
  input wire logic i_narrow_output,
  input wire logic [15:0] i_ch0_q,
  input wire logic [31:0] i_ch0,
  input wire logic [32:0] i_q_current,
  input wire logic [31:0] i_channel_addr,
  input wire logic i_pad_q,
  input wire logic [p_cache_read_width-1:0] i_word_buf,
  input wire logic [31:0] i_word_addr,
  input wire logic i_word_valid,
  input wire logic [31:0] i_decode_index,
  input wire logic [31:0] i_decode_inner,
  input wire logic i_cache_req_ready,
  input wire logic i_cache_rsp_valid,
  input wire logic i_cache_rsp_error,
  input wire logic [p_word_shift+1:0] i_byte_offset_sum,
  input wire logic i_descriptor_response_forward,
  input wire logic i_incoming_next_tile_fast,
  input wire logic i_incoming_next_position_fast,
  input wire logic i_incoming_skip_tap,
  input wire logic [15:0] i_window_next_ch,
  input wire logic [p_cache_read_width-1:0] i_cache_rsp_data,
  input wire logic i_pred_cfg_busy,
  input wire logic i_cache_cfg_pending,
  input wire logic i_pred_cfg_pending,
  input wire logic i_geometry_tile,
  input wire logic i_incoming_fast,
  input wire logic i_incoming_padding,
  input wire logic [31:0] i_incoming_addr,
  input wire logic [9:0][31:0] i_incoming_address_candidates,
  input wire logic [15:0] i_current_q_remainder,
  input wire logic i_next_word_o_equal,
  input wire logic i_incoming_word_o_equal,
  input wire logic i_incoming_live_word_o_equal,
  input wire logic i_row_base_valid,
  input wire logic i_coordinate_address_valid,
  input wire logic i_row_coordinate_valid,
  input wire logic i_next_row_padding,
  input wire logic i_next_tap_padding,
  input wire logic i_incoming_tap_wrap_q,
  input wire logic [31:0] i_next_row_addr,
  input wire logic [31:0] i_next_tap_addr,
  input wire logic i_channel_accept_fire,
  input wire logic [p_prepared_tile_width-1:0] i_committing_tile_packed,
  input wire logic i_tile_commit,
  input wire logic i_committing_saved_word_hit,
  input wire logic i_committing_live_word_hit,
  input wire logic [1:0] i_next_row_word_match,
  input wire logic [1:0] i_incoming_advanced_word_match,
  input wire logic i_group_shape_o_valid,
  output logic signed [15:0] o_wr_data [p_lanes],
  output logic [p_lanes-1:0] o_wr_mask,
  output logic [5:0][15:0] o_group_range_channel,
  output logic [16:0] o_initial_group_remaining,
  output logic [5:0][p_saved_group_lanes:0] o_group_range_next,
  output logic [32:0] o_cfg_next_group,
  output logic [32:0] o_cfg_skip_group,
  output logic [p_lanes-1:0] o_chunk_lane_allowed,
  output logic [p_lanes:0] o_chunk_selected,
  output logic o_chunk_reaches_end,
  output logic [15:0] o_ch_q,
  output logic [31:0] o_addr,
  output logic o_current_word_hit,
  output logic [p_chunk_count_w-1:0] o_chunk_count,
  output logic o_cache_req_valid,
  output logic o_cache_rsp_ready,
  output logic o_stream_next_request,
  output logic o_next_row_request,
  output logic o_request_stream_context,
  output logic o_request_row_context,
  output logic o_request_tap_context,
  output logic o_active_after_chunk,
  output logic o_incoming_context,
  output logic o_incoming_word_hit,
  output logic [1:0] o_incoming_tile_group_fits,
  output logic [31:0] o_cache_req_addr,
  output logic [31:0] o_stream_request_addr,
  output logic o_cache_config_valid,
  output logic o_incoming_tap_wrap,
  output logic [32:0] o_next_q_current,
  output logic o_group_end_o_equal,
  output conv_im2col_frontend_pkg::st_t o_stream_advance_state
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
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
  (* keep = 1 *) logic [p_lanes-1:0] chunk_static_end;
  logic [p_lanes-1:0] chunk_data_allowed;
  logic [4:0] address_update_select;
  logic [31:0] address_update_value;
  logic address_stream_write;
  logic address_column_advance;
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
  logic [p_lanes:0] step_word_boundary;
  logic [p_lanes:0] step_saved_hit;
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
  logic range_commit_context;
  st_t stream_static_state;
  logic stream_request_selected;
  logic stream_row_selected;
  logic stream_tap_selected;
  logic stream_read_accepted;
  st_t stream_accepted_state;
  assign committing_tile = prepared_tile_t'(i_committing_tile_packed);

  assign o_chunk_selected[0] = p_contiguous_chunk ? !o_chunk_lane_allowed[0] : !(|o_chunk_lane_allowed);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_chunk_selected
    if (step == p_lanes) begin : g_last
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1];
    end else if (p_contiguous_chunk) begin : g_contiguous
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1] && !o_chunk_lane_allowed[step];
    end else begin : g_lower
      assign o_chunk_selected[step] = o_chunk_lane_allowed[step-1] && !(|o_chunk_lane_allowed[p_lanes-1:step]);
    end
  end
  if (p_chunk_count_w + 1 < 32) begin : g_byte_address
    localparam int p_step_width = p_chunk_count_w + 1;
    logic [p_step_width:0] address_low;
    logic [31-p_step_width:0] address_high_next;
    logic [32-p_step_width:0] address_high_sum;
    logic unused_address_carry;

    // 块内字节步长仅影响低位，高位加一提前完成。
    if (p_lanes <= 16) begin : g_parallel_byte_step
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
          address_low |= {(p_step_width+1){o_chunk_selected[step]}} & low_for_step[step];
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

  if (p_lanes <= 16 && p_chunk_count_w < 16) begin : g_channel_step
    (* keep = 1 *) logic [p_lanes:0][p_chunk_count_w:0] low_for_step;
    logic [p_chunk_count_w:0] channel_low;
    logic [16-p_chunk_count_w:0] channel_high_next;
    // 通道低位提前计算固定步长，高位加一与传输数量选择并行。
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      assign low_for_step[step] = {1'b0, o_ch_q[p_chunk_count_w-1:0]} + (p_chunk_count_w+1)'(step);
    end
    always_comb begin
      channel_low = '0;
      for (int step = 0; step <= p_lanes; step++)
        channel_low |= {(p_chunk_count_w+1){o_chunk_selected[step]}} & low_for_step[step];
    end
    assign channel_high_next = {1'b0, o_ch_q[15:p_chunk_count_w]} + (17-p_chunk_count_w)'(1);
    assign channel_position_sum = {
        channel_low[p_chunk_count_w] ? channel_high_next : {1'b0, o_ch_q[15:p_chunk_count_w]},
        channel_low[p_chunk_count_w-1:0]};
  end else begin : g_channel_step_wide
    assign channel_position_sum = {1'b0, o_ch_q} + 17'(o_chunk_count);
  end
  assign {unused_channel_position_carry, next_channel} = channel_position_sum;

  // 当前组的剩余通道数共用一次扩展减法，窗口上下文保存对应剩余值。
  logic [16:0] initial_group_remaining_value;
  logic unused_initial_group_carry;
  parallel_prefix_add #(.p_width(17), .p_group_width(8), .p_preserve_groups(1'b1)) u_initial_group_remaining (
    .i_a({1'b0, i_c.group_c}), .i_b(~{1'b0, i_ch0_q}), .i_carry(1'b1),
    .o_sum(initial_group_remaining_value), .o_carry(unused_initial_group_carry)
  );
  always_comb begin
    case (^{i_c.group_c, i_ch0_q})
      1'b0, 1'b1: o_initial_group_remaining = initial_group_remaining_value;
      default: o_initial_group_remaining = 'x;
    endcase
  end
  for (genvar source = 0; source < 2; source++) begin : g_tile_group_range
    logic [15:0] first_channel;
    logic [16:0] requested_columns;
    assign first_channel = source == 0 ? i_window_next_ch : i_ch0_q;
    assign requested_columns = i_tile_cols == '0 ? 17'(p_size) : 17'(i_tile_cols);
    if (source == 0 && p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_remaining
      logic [16:0] remaining;
      (* keep = 1 *) logic full_tile_fits, explicit_tile_fits;
      assign remaining = source == 0 ? i_window_group_remaining_q : o_initial_group_remaining;
      // 缺省列数与显式列数分别检查，列数选择只作用于最终范围标志。
      assign full_tile_fits = !remaining[16] && 17'(p_size) <= remaining;
      assign explicit_tile_fits = !remaining[16] && 17'(i_tile_cols) <= remaining;
      assign o_incoming_tile_group_fits[source] = i_tile_cols == '0 ? full_tile_fits : explicit_tile_fits;
    end else if (p_tile_count_w < 16 && p_rw <= p_tile_count_w) begin : g_short_remaining
      localparam int p_high_w = 16 - p_tile_count_w;
      logic low_borrow, high_before, high_equal, high_next_equal;
      logic low_less, default_allows, candidate_fits;

      // 五位余量按三个低位和两个高位并行求界，借位只参与末端选择。
      if (p_tile_count_w == 5 && p_size == 16) begin : g_low_five
        conv_tile_group_low5 u_low (
          .i_group(i_c.group_c[4:0]), .i_first(first_channel[4:0]),
          .i_columns(5'(i_tile_cols)), .o_borrow(low_borrow),
          .o_less(low_less), .o_default_allows(default_allows)
        );
      end else begin : g_low_general
        logic [p_tile_count_w-1:0] remaining_low;
        logic unused_low_equal;
        assign remaining_low = i_c.group_c[p_tile_count_w-1:0] - first_channel[p_tile_count_w-1:0];
        assign low_borrow = i_c.group_c[p_tile_count_w-1:0] < first_channel[p_tile_count_w-1:0];
        parallel_unsigned_compare #(.p_width(p_tile_count_w)) u_low (
          .i_a(remaining_low), .i_b(p_tile_count_w'(i_tile_cols)),
          .o_less(low_less), .o_equal(unused_low_equal)
        );
        assign default_allows = (|i_tile_cols) || p_tile_count_w'(p_size) <= remaining_low;
      end
      parallel_unsigned_compare #(.p_width(p_high_w)) u_high (
        .i_a(first_channel[15:p_tile_count_w]), .i_b(i_c.group_c[15:p_tile_count_w]),
        .o_less(high_before), .o_equal(high_equal)
      );
      increment_equal #(.p_width(p_high_w)) u_high_next (
        .i_a(first_channel[15:p_tile_count_w]), .i_target(i_c.group_c[15:p_tile_count_w]),
        .o_equal(high_next_equal)
      );
      conv_tile_group_range_result u_result (
        .i_high_before(high_before), .i_high_equal(high_equal), .i_high_next_equal(high_next_equal),
        .i_low_borrow(low_borrow), .i_low_less(low_less), .i_default_allows(default_allows),
        .o_fits(candidate_fits)
      );
`ifdef SYNTHESIS
      assign o_incoming_tile_group_fits[source] = candidate_fits;
`else
      logic [p_tile_count_w:0] column_end_low;
      logic low_within, comparison_value;
      assign column_end_low = {1'b0, first_channel[p_tile_count_w-1:0]} +
          (p_tile_count_w+1)'(requested_columns);
      assign low_within = column_end_low[p_tile_count_w-1:0] <= i_c.group_c[p_tile_count_w-1:0];
      always_comb begin
        case (^{first_channel, i_c.group_c, i_tile_cols})
          1'b0, 1'b1: comparison_value = candidate_fits;
          default: comparison_value =
              (high_before && (!column_end_low[p_tile_count_w] || !high_next_equal || low_within)) ||
              (high_equal && !column_end_low[p_tile_count_w] && low_within);
        endcase
      end
      assign o_incoming_tile_group_fits[source] = comparison_value;
`endif
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

  if (p_lanes <= 16 && p_lanes <= p_cache_read_bytes) begin : g_short_word_advance
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
    assign next_byte_saved_hit = |(o_chunk_selected & step_saved_hit);
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
  parallel_prefix_add #(.p_width(32-p_word_shift), .p_group_width(8), .p_preserve_groups(1'b1)) u_stream_request_word (
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
  // 请求坐标由运行阶段提前选择，传输握手控制请求有效信号。
  assign o_request_stream_context = stream_context;
  assign o_request_row_context =
      (stream_context || i_state[$clog2(ZERO_STREAM)]) && row_request_eligible;
  assign o_request_tap_context = p_register_cache_request &&
      (stream_context || i_state[$clog2(ZERO_STREAM)]) &&
      !o_chunk_reaches_end && o_group_end_o_equal;
  // 字命中标志与当前地址同时保存，请求有效条件只读取一位状态。
  assign o_current_word_hit = p_register_descriptor ? addr_word_hit_q :
    i_word_valid && i_word_addr == {o_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  assign next_tap_saved_hit = i_state[$clog2(WAIT_WORD)] ? i_next_word_o_equal :
    i_word_valid && i_word_addr == {i_next_tap_addr[31:p_word_shift], {p_word_shift{1'b0}}};
  // 字地址先保存，再在检查周期比较标签与有效位。

  assign channel_word_equal = o_addr[31:p_word_shift] == i_word_addr[31:p_word_shift];
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
  // 三类请求分别形成资格，地址和命中比较不接收最终传输条件。
  conv_im2col_request_control #(
    .p_size(p_size), .p_rw(p_rw), .p_register_descriptor(p_register_descriptor)
  ) u_request_control (
    .i_tile_valid(i_tile_valid), .i_tile_ready(i_tile_ready),
    .i_incoming_fast(i_incoming_fast), .i_incoming_padding(i_incoming_padding),
    .i_incoming_word_hit(o_incoming_word_hit),
    .i_tile_rows(i_tile_rows), .i_tile_cols(i_tile_cols),
    .i_tile_q_before_end(i_tile_q_before_end), .i_tile_rows_in_range(i_tile_rows_in_range),
    .i_fetch(i_state[$clog2(FETCH)]), .i_current_word_hit(o_current_word_hit),
    .i_wr_valid(i_wr_valid), .i_wr_ready(i_wr_ready),
    .i_stream_request_eligible(stream_request_eligible),
    .i_row_request_eligible(row_request_eligible), .i_tap_selected(stream_tap_selected),
    .o_cache_req_valid(o_cache_req_valid)
  );
  assign o_incoming_context=!p_register_descriptor && i_tile_valid &&
    (i_state[$clog2(IDLE)] || ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] || i_state[$clog2(ZERO_STREAM)]) && i_wr_last));
  assign o_cache_req_addr=o_request_tap_context ? i_next_tap_addr :
      o_incoming_context ? i_incoming_addr : o_request_row_context ? i_next_row_addr :
      stream_context ? stream_request_addr : o_addr;
  assign o_stream_request_addr = stream_request_addr;
  assign o_cache_rsp_ready = i_state[$clog2(WAIT_WORD)] && (i_wr_ready || i_cache_rsp_error);
  assign o_cache_config_valid = i_cache_cfg_pending && !i_pred_cfg_pending && !i_pred_cfg_busy;
  // 各种通道来源并行计算组内范围，接收边沿只选择相应标志。
  assign o_group_range_channel[0] = 16'd0;
  assign o_group_range_channel[1] = i_ch0_q;
  assign o_group_range_channel[2] = i_q0[15:0] & i_last_group_channel_q;
  assign o_group_range_channel[3] = i_current_q_remainder;
  assign o_group_range_channel[4] = 16'(i_decode_inner);
  assign o_group_range_channel[5] = next_channel;

  // 传输到组末的条件直接检查加法等式，保留第十七位的回绕语义。
  if (p_lanes <= 16) begin : g_group_end_by_lane
    logic [p_lanes:0] step_o_equal;
    (* keep = 1 *) logic [p_lanes:0] selected_end;
    logic [2:0] format_group_end;
    logic parallel_group_end;

    // 各种通道数的组末关系提前计算，当前周期只选择最后有效通道。
    for (genvar step = 0; step <= p_lanes; step++) begin : g_step
      // 范围标志与通道坐标同拍保存，相邻边界的转换直接表示剩余长度。
      if (step == 0) begin : g_zero_remaining
        assign step_o_equal[step] = !group_range_q[0];
      end else begin : g_remaining_boundary
        assign step_o_equal[step] = group_range_q[step-1] && !group_range_q[step];
      end
      assign selected_end[step] = o_chunk_selected[step] && step_o_equal[step];
    end
    // 三种字节覆盖方式分别完成组末判断，运行状态只选择最终一位结果。
    for (genvar format_index = 0; format_index < 3; format_index++) begin : g_format
      logic [p_lanes-1:0] available;
      assign available = lane_context_allowed & column_lane_allowed_q[p_lanes-1:0] &
          (format_index == 0 ? {p_lanes{1'b1}} :
           format_index == 1 ? word_lane_s8 : word_lane_s16);
      conv_im2col_mask_end #(.p_lanes(p_lanes), .p_contiguous(p_contiguous_chunk)) u_end (
        .i_available(available), .i_boundary(step_o_equal), .o_end(format_group_end[format_index])
      );
    end
    conv_im2col_group_end_select u_format_end (
      .i_word_output(i_word_output_q), .i_input_s16(i_c.input_s16),
      .i_end(format_group_end), .o_end(parallel_group_end)
    );
    always_comb begin
      o_group_end_o_equal = |selected_end;
      case (^{lane_context_allowed, column_lane_allowed_q, word_lane_s8, word_lane_s16,
               step_o_equal, i_word_output_q, i_c.input_s16})
        1'b0, 1'b1: o_group_end_o_equal = parallel_group_end;
        default: ;
      endcase
    end
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

  if (p_lanes <= 16) begin : g_short_group_lane
    localparam int p_lane_compare_width = $clog2(p_saved_group_lanes+1);
    logic [p_lane_compare_width:0] configured_remaining;
    (* keep = 1 *) logic configured_high_equal, configured_high_next_equal, configured_high_last;
    logic configured_high_nonzero;

    assign configured_remaining = {1'b0, i_cfg.group_c[p_lane_compare_width-1:0]} -
        {1'b0, o_ch_q[p_lane_compare_width-1:0]};
    assign configured_high_equal = i_cfg.group_c[15:p_lane_compare_width] == o_ch_q[15:p_lane_compare_width];
    assign configured_high_last = &o_ch_q[15:p_lane_compare_width];
    increment_equal #(.p_width(16-p_lane_compare_width)) u_configured_high_next (
          .i_a(o_ch_q[15:p_lane_compare_width]), .i_target(i_cfg.group_c[15:p_lane_compare_width]),
          .o_equal(configured_high_next_equal)
        );
    // 低段借位只选择高段相等关系，高段比较与低段减法并行。
    assign configured_high_nonzero = configured_remaining[p_lane_compare_width] ?
        !configured_high_next_equal || configured_high_last : !configured_high_equal;
    // 常量通道边界仅比较低位，高位非零条件由全部通道共用。
    for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_cfg_lane
      assign group_range_cfg[lane] = configured_high_nonzero ||
          p_lane_compare_width'(lane) < configured_remaining[p_lane_compare_width-1:0];
    end
    // 配置及译码来源共用完整剩余数量，流式递增提前形成每种步长的范围。
    for (genvar source = 0; source < 6; source++) begin : g_source
      if (source == 5) begin : g_stream_advance
        localparam int p_range_low_w = $clog2(p_lanes+p_saved_group_lanes+1);
        (* keep = 1 *) logic [p_range_low_w:0] remaining;
        (* keep = 1 *) logic remaining_high_equal, remaining_high_next_equal;
        logic remaining_high_nonzero;
        logic channel_high_last;
        logic [p_lanes:0] channel_wrap;
        logic [p_saved_group_lanes:0][p_lanes:0] selected_range;
        logic [p_saved_group_lanes:0][p_lanes:0] selected_transfer_range;
        logic [p_saved_group_lanes:0][p_lanes:0] transfer_range_allowed;
        logic [p_lanes:0] transfer_ends;
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
        borrow_select_subtract #(.p_width(p_range_low_w)) u_remaining (
          .i_a(i_c.group_c[p_range_low_w-1:0]), .i_b(o_ch_q[p_range_low_w-1:0]),
          .o_difference(remaining)
        );
        assign remaining_high_equal = i_c.group_c[15:p_range_low_w] == o_ch_q[15:p_range_low_w];
        increment_equal #(.p_width(16-p_range_low_w)) u_remaining_high_next (
          .i_a(o_ch_q[15:p_range_low_w]), .i_target(i_c.group_c[15:p_range_low_w]),
          .o_equal(remaining_high_next_equal)
        );
        assign remaining_high_nonzero = remaining[p_range_low_w] ?
            !remaining_high_next_equal : !remaining_high_equal;
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
          assign transfer_ends[step] = reaches_group_end;
          for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_lane
            logic range_allowed;
            conv_channel_range_compare #(
              .p_width(p_range_low_w), .p_step(step), .p_lane(lane)
            ) u_range (
              .i_remaining_low(remaining[p_range_low_w-1:0]),
              .i_channel_low(o_ch_q[p_range_low_w-1:0]),
              .i_remaining_borrow(remaining[p_range_low_w]),
              .i_high_nonzero(remaining_high_nonzero),
              .i_channel_high_last(channel_high_last), .o_allowed(range_allowed)
            );
            assign transfer_range_allowed[lane][step] = range_allowed;
            assign selected_range[lane][step] = o_chunk_selected[step] && range_allowed;
            // 每个固定步长先选择组切换或组内递增，再由当前传输数量选取。
            assign selected_transfer_range[lane][step] = transfer_selected[step] &&
                (reaches_group_end ? o_group_range_next[0][lane] : range_allowed);
          end
        end
        // 组首与组内递增分别归并，每个局部结果只组合两个传输候选。
        localparam int p_transfer_pairs = (p_lanes+2)/2;
        localparam int p_restart_groups = (p_lanes+3)/3;
        (* keep = 1 *) logic [p_restart_groups-1:0] restart_group;
        logic restart_any;
        for (genvar group_index = 0; group_index < p_restart_groups; group_index++) begin : g_restart
          logic [2:0] selected;
          for (genvar item = 0; item < 3; item++) begin : g_item
            localparam int p_step = 3*group_index+item;
            if (p_step <= p_lanes) begin : g_present
              assign selected[item] = transfer_selected[p_step] && transfer_ends[p_step];
            end else begin : g_unused
              assign selected[item] = 1'b0;
            end
          end
          assign restart_group[group_index] = |selected;
        end
        assign restart_any = |restart_group;
        for (genvar lane = 0; lane <= p_saved_group_lanes; lane++) begin : g_select_lane
          (* keep = 1 *) logic [p_transfer_pairs-1:0] advance_pair;
          logic reduced_range;
          for (genvar pair = 0; pair < p_transfer_pairs; pair++) begin : g_pair
            logic [1:0] selected;
            for (genvar item = 0; item < 2; item++) begin : g_item
              localparam int p_step = 2*pair+item;
              if (p_step <= p_lanes) begin : g_present
                assign selected[item] = transfer_selected[p_step] && !transfer_ends[p_step] &&
                    transfer_range_allowed[lane][p_step];
              end else begin : g_unused
                assign selected[item] = 1'b0;
              end
            end
            assign advance_pair[pair] = |selected;
          end
          assign reduced_range = (|advance_pair) || (restart_any && o_group_range_next[0][lane]);
          assign o_group_range_next[source][lane] = |selected_range[lane];
          always_comb begin
            group_transfer_range[lane] = |selected_transfer_range[lane];
            case (^{transfer_selected, transfer_ends, transfer_range_allowed[lane], o_group_range_next[0][lane]})
              1'b0, 1'b1: group_transfer_range[lane] = reduced_range;
              default: ;
            endcase
          end
        end
      end else begin : g_direct_range
        logic [p_lane_compare_width:0] remaining;
        (* keep = 1 *) logic high_equal, high_next_equal, high_last;
        logic high_nonzero;
        assign remaining = {1'b0, i_c.group_c[p_lane_compare_width-1:0]} -
            {1'b0, o_group_range_channel[source][p_lane_compare_width-1:0]};
        assign high_equal = i_c.group_c[15:p_lane_compare_width] ==
            o_group_range_channel[source][15:p_lane_compare_width];
        assign high_last = &o_group_range_channel[source][15:p_lane_compare_width];
        increment_equal #(.p_width(16-p_lane_compare_width)) u_high_next (
          .i_a(o_group_range_channel[source][15:p_lane_compare_width]), .i_target(i_c.group_c[15:p_lane_compare_width]),
          .o_equal(high_next_equal)
        );
        assign high_nonzero = remaining[p_lane_compare_width] ?
            !high_next_equal || high_last : !high_equal;
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
      localparam int p_lane = lane;
      // 数据区和补零区共用行末位置，各格式分别检查缓存字覆盖范围。
      conv_im2col_chunk_lane #(.p_narrow_lane(p_lane < p_narrow_lanes)) u_static_end (
        .i_narrow_output(i_narrow_output),
        .i_column_allowed(column_lane_allowed_q[p_lane]),
        .i_next_column_allowed(column_lane_allowed_q[p_lane+1]),
        .i_past_active(i_past_active_q), .i_group_allowed(group_lane_allowed[p_lane]),
        .i_active_allowed(active_lane_allowed_q[p_lane]), .o_end(chunk_static_end[p_lane])
      );
      assign chunk_end_s8[p_lane] = chunk_static_end[p_lane] && allowed_s8;
      assign chunk_end_s16[p_lane] = chunk_static_end[p_lane] && allowed_s16;
    end else begin : g_wrapped_column
      assign chunk_end_s8[lane] = 1'b0;
      assign chunk_end_s16[lane] = 1'b0;
      assign chunk_static_end[lane] = 1'b0;
    end
  end
  if (p_tile_count_w >= p_chunk_count_w) begin : g_direct_chunk_end
    logic [p_lanes-1:0][2:0] format_candidate;
    logic [2:0] format_end;
    // 三种格式独立完成通道归并，运行状态只参与六输入的最终选择。
    for (genvar lane = 0; lane < p_lanes; lane++) begin : g_format_candidate
      assign format_candidate[lane] = {1'b1, word_lane_s16[lane], word_lane_s8[lane]};
    end
    onehot_mux #(.p_choices(p_lanes), .p_width(3)) u_format_end (
      .i_select(chunk_static_end), .i_data(format_candidate), .o_data(format_end)
    );
    conv_im2col_chunk_end_select u_end (
      .i_first_column_allowed(column_lane_allowed_q[0]),
      .i_word_output(i_word_output_q), .i_input_s16(i_c.input_s16),
      .i_format_end(format_end), .o_end(o_chunk_reaches_end)
    );
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
  if (p_lanes <= 16 && p_cache_read_bytes <= 16) begin : g_parallel_formatter
    (* keep = 1 *) logic [1:0][p_cache_read_bytes-1:0][8:0] source_corrected;

    // 返回字与保存字分别完成偏移运算，地址和格式只选择最终候选。
    for (genvar source = 0; source < 2; source++) begin : g_source
      for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_byte
        logic [7:0] sample;
        assign sample = source == 0 ? i_cache_rsp_data[8*byte_index +: 8] :
            i_word_buf[8*byte_index +: 8];
        conv_im2col_sample_sum u_offset (
          .i_a({sample[7], sample}), .i_b(i_c.input_offset[8:0]),
          .o_sum(source_corrected[source][byte_index])
        );
      end
    end
    for (genvar data_lane = 0; data_lane < p_lanes; data_lane++) begin : g_lane
      localparam int p_s8_candidates = p_cache_read_bytes > data_lane ? p_cache_read_bytes - data_lane : 0;
      localparam int p_s16_candidates = p_cache_read_bytes > 2*data_lane ? p_cache_read_bytes - 2*data_lane : 0;
      localparam int p_other_candidates = p_s8_candidates + 2*p_s16_candidates;
      localparam int p_direct_candidates = p_s8_candidates + 2;
      logic [p_direct_candidates-1:0] direct_selected;
      logic [p_direct_candidates-1:0][15:0] direct_value;
      logic [15:0] other_value, parallel_value;

      // 返回字的八位样本直接参与末级选择，保存字和十六位格式并行形成完整结果。
      for (genvar byte_index = data_lane; byte_index < p_cache_read_bytes; byte_index++) begin : g_direct_s8
        localparam int p_candidate = byte_index - data_lane;
        assign direct_selected[p_candidate] =
            o_addr[p_word_shift-1:0] == p_word_shift'(byte_index - data_lane) &&
            i_state[$clog2(WAIT_WORD)] && !i_c.input_s16 && stream_context && o_wr_mask[data_lane];
        assign direct_value[p_candidate] =
            {{7{source_corrected[0][byte_index][8]}}, source_corrected[0][byte_index]};
      end
      if (p_other_candidates > 0) begin : g_other_values
        logic [p_other_candidates-1:0] selected;
        logic [p_other_candidates-1:0][15:0] candidate;
        for (genvar byte_index = data_lane; byte_index < p_cache_read_bytes; byte_index++) begin : g_saved_s8
          localparam int p_candidate = byte_index - data_lane;
          assign selected[p_candidate] =
              o_addr[p_word_shift-1:0] == p_word_shift'(byte_index - data_lane) &&
              !i_state[$clog2(WAIT_WORD)] && !i_c.input_s16 && stream_context && o_wr_mask[data_lane];
          assign candidate[p_candidate] =
              {{7{source_corrected[1][byte_index][8]}}, source_corrected[1][byte_index]};
        end
        for (genvar source = 0; source < 2; source++) begin : g_source
          logic [p_cache_read_width-1:0] word_value;
          assign word_value = source == 0 ? i_cache_rsp_data : i_word_buf;
          for (genvar byte_index = 2*data_lane; byte_index < p_cache_read_bytes; byte_index++) begin : g_s16
            localparam int p_candidate = p_s8_candidates + 2*(byte_index - 2*data_lane) + source;
            assign selected[p_candidate] =
                o_addr[p_word_shift-1:0] == p_word_shift'(byte_index - 2*data_lane) &&
                (source == 0 ? i_state[$clog2(WAIT_WORD)] : !i_state[$clog2(WAIT_WORD)]) &&
                i_c.input_s16 && stream_context && o_wr_mask[data_lane];
            assign candidate[p_candidate] = 16'(word_value >> (8*byte_index));
          end
        end
        conv_im2col_formatter_mux #(.p_choices(p_other_candidates), .p_width(16)) u_other (
          .i_select(selected), .i_data(candidate), .o_data(other_value)
        );
      end else begin : g_empty_other
        assign other_value = '0;
      end
      // 字尾之外的八位样本为零，其偏移结果仍参与完整输出语义。
      assign direct_selected[p_s8_candidates] =
          (data_lane >= p_cache_read_bytes || {1'b0, o_addr[p_word_shift-1:0]} >=
              (p_word_shift+1)'(p_cache_read_bytes - data_lane)) &&
          !i_c.input_s16 && stream_context && o_wr_mask[data_lane];
      assign direct_value[p_s8_candidates] =
          {{7{i_c.input_offset[8]}}, i_c.input_offset[8:0]};
      assign direct_selected[p_s8_candidates+1] = 1'b1;
      assign direct_value[p_s8_candidates+1] = other_value;
      conv_im2col_formatter_mux #(.p_choices(p_direct_candidates), .p_width(16)) u_result (
        .i_select(direct_selected), .i_data(direct_value), .o_data(parallel_value)
      );
      always_comb begin
        o_wr_data[data_lane] = '0;
        // 未知选择值沿用字移位和符号运算的四态语义。
        case (^{i_cache_rsp_data, i_word_buf, i_c.input_offset[8:0], i_c.input_s16,
                o_addr[p_word_shift-1:0], i_state[$clog2(WAIT_WORD)], stream_context, o_wr_mask[data_lane]})
          1'b0, 1'b1: o_wr_data[data_lane] = $signed(parallel_value);
          default: begin
            if (stream_context && o_wr_mask[data_lane]) begin
              if (i_c.input_s16) o_wr_data[data_lane] = $signed(16'(selected_word >> (data_lane*16)));
              else o_wr_data[data_lane] = $signed(corrected_s8_value[data_lane]);
            end
          end
        endcase
      end
    end
  end else begin : g_wide_formatter
    always_comb begin
      for (int l=0;l<p_lanes;l++) begin
        o_wr_data[l]=0;
        if ((i_state[$clog2(STREAM)] || i_state[$clog2(WAIT_WORD)]) && o_wr_mask[l]) begin
          if (i_c.input_s16) o_wr_data[l]=$signed(16'(selected_word>>(l*16)));
          else o_wr_data[l]=$signed(corrected_s8_value[l]);
        end
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
  assign group_range_stream_value = p_lanes <= 16 ?
      (group_range_row_value | ({(p_saved_group_lanes+1){!o_chunk_reaches_end}} & group_transfer_range)) :
      (group_range_row_value | group_range_restart_value | group_range_advance_value);

  // 流式范围的保存资格与三种候选值并行计算，返回有效只控制寄存器写入。

  if (!(p_lanes <= 16)) begin : g_qualified_range_write
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
  logic [3:0] range_decode_select;
  // 译码选择保持状态优先次序，其数据准备与配置及输出握手独立。
  always_comb begin
    range_decode_write = 1'b0;
    range_decode_value = o_group_range_next[4];
    range_decode_select = 4'b1000;
    unique case (1'b1)
      i_state[$clog2(P_DECODE)], i_state[$clog2(P_START)], i_state[$clog2(P_WAIT)]: ;
      i_state[$clog2(Q_DECODE)]: begin
        if (i_q0 == 32'd0) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[0];
          range_decode_select = 4'b0001;
        end else if (i_group_shape_o_valid) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[2];
          range_decode_select = 4'b0010;
        end else if (i_c.group_c == 16'd3 && i_q0 < 32'd27) begin
          range_decode_write = 1'b1;
          range_decode_value = o_group_range_next[3];
          range_decode_select = 4'b0100;
        end
      end
      i_state[$clog2(Q_START)]: ;
      i_state[$clog2(Q_WAIT)]: begin
        if (i_decode_index == i_q0) range_decode_write = 1'b1;
      end
      default: ;
    endcase
  end
  // A new descriptor owns the range update when the previous tile completes.
  assign range_update_select[0] = range_decode_write;
  assign range_update_select[1] = i_cfg_valid && i_cfg_ready;
  assign range_update_select[2] = i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign range_update_select[3] = !i_tile_commit &&
      i_wr_valid && range_stream_allowed;
  assign range_commit_context = p_register_descriptor ? range_update_select[2] :
      o_incoming_context && i_tile_admission_ready;
  if (p_lanes <= 16) begin : g_range_data_choice
    logic [3:0] range_value_select;
    logic [6:0] range_source_select;
    (* keep = 1 *) logic [7:0] range_data_select;
    logic [7:0][p_saved_group_lanes:0] range_candidate;
    logic [p_saved_group_lanes:0] selected_range_value;
    // 先确定范围来源，再选择各来源独立准备的通道范围。
    always_comb begin
      range_value_select = 4'b0001;
      case (1'b1)
        range_update_select[1]: range_value_select = 4'b0010;
        (!p_register_descriptor &&
            (i_state[$clog2(Q_DECODE)] || i_state[$clog2(Q_WAIT)])):
          range_value_select = 4'b1000;
        range_commit_context: range_value_select = 4'b0100;
        range_update_select[0]: range_value_select = 4'b1000;
        default: ;
      endcase
    end
    assign range_source_select[2:0] = range_value_select[2:0];
    assign range_source_select[6:3] = {4{range_value_select[3]}} & range_decode_select;
    assign range_data_select[6:1] = range_source_select[6:1];
    assign range_data_select[0] = range_source_select[0] && !o_chunk_reaches_end;
    assign range_data_select[7] = range_source_select[0] && o_chunk_reaches_end;
    assign range_candidate[0] = group_transfer_range;
    assign range_candidate[1] = group_range_cfg;
    assign range_candidate[2] = committing_tile.channel_range;
    assign range_candidate[3] = o_group_range_next[0];
    assign range_candidate[4] = o_group_range_next[2];
    assign range_candidate[5] = o_group_range_next[3];
    assign range_candidate[6] = o_group_range_next[4];
    assign range_candidate[7] = o_group_range_next[1];
    onehot_mux #(.p_choices(8), .p_width(p_saved_group_lanes+1)) u_range_data (
      .i_select(range_data_select), .i_data(range_candidate), .o_data(selected_range_value)
    );
    always_comb begin
      range_update_value = '0;
      unique case (1'b1)
        range_source_select[0]: range_update_value = group_range_stream_value;
        range_source_select[1]: range_update_value = group_range_cfg;
        range_source_select[2]: range_update_value = committing_tile.channel_range;
        range_source_select[3]: range_update_value = o_group_range_next[0];
        range_source_select[4]: range_update_value = o_group_range_next[2];
        range_source_select[5]: range_update_value = o_group_range_next[3];
        range_source_select[6]: range_update_value = o_group_range_next[4];
        default: ;
      endcase
      // 来源含未知值时保留优先选择的四态语义。
      case (^{range_data_select, range_candidate})
        1'b0, 1'b1: range_update_value = selected_range_value;
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

  // 通道数据按运行阶段预选，缓存返回只控制最终保存。
  logic channel_write_enable;
  logic [15:0] channel_store_value;
  logic [3:0] channel_data_select;
  logic [3:0][15:0] channel_data_candidate;
  logic [15:0] channel_selected_value, channel_stream_value, channel_decode_value;
  logic channel_phase_write, channel_commit_context;
  assign channel_value = i_channel_accept_fire ? 16'(committing_tile.channel) : channel_update;
  assign channel_commit_context = p_register_descriptor ? i_channel_accept_fire :
      o_incoming_context && i_tile_admission_ready;
  assign channel_stream_value = o_chunk_reaches_end ? 16'(i_ch0) :
      o_group_end_o_equal ? 16'd0 : next_channel;
  always_comb begin
    channel_decode_value = 16'd0;
    if (i_q0 != 32'd0) begin
      if (i_group_shape_o_valid) channel_decode_value = o_group_range_channel[2];
      else if (i_c.group_c == 16'd3 && i_q0 < 32'd27)
        channel_decode_value = i_current_q_remainder;
    end
    channel_phase_write = 1'b0;
    channel_data_select = 4'b0000;
    unique case (1'b1)
      i_state[$clog2(WAIT_WORD)], i_state[$clog2(STREAM)], i_state[$clog2(ZERO_STREAM)]: begin
        channel_data_select = 4'b0001;
        channel_phase_write =
            !(i_state[$clog2(WAIT_WORD)] && i_cache_rsp_valid && i_cache_rsp_error) &&
            i_wr_valid && i_wr_ready &&
            ((o_chunk_reaches_end && !i_row_last_q) ||
             (!o_chunk_reaches_end && i_col_idx < i_active_cols_q &&
              p_tile_count_w'(o_chunk_count) < active_remaining));
      end
      i_state[$clog2(Q_DECODE)]: begin
        channel_data_select = 4'b0010;
        channel_phase_write = i_q0 == 32'd0 || i_group_shape_o_valid ||
            (i_c.group_c == 16'd3 && i_q0 < 32'd27);
      end
      i_state[$clog2(Q_WAIT)]: begin
        channel_data_select = 4'b0100;
        channel_phase_write = i_decode_index == i_q0;
      end
      default: ;
    endcase
    if (channel_commit_context) channel_data_select = 4'b1000;
  end
  assign channel_data_candidate[0] = channel_stream_value;
  assign channel_data_candidate[1] = channel_decode_value;
  assign channel_data_candidate[2] = 16'(i_decode_inner);
  assign channel_data_candidate[3] = 16'(committing_tile.channel);
  onehot_mux #(.p_choices(4), .p_width(16)) u_channel_data (
    .i_select(channel_data_select), .i_data(channel_data_candidate), .o_data(channel_selected_value)
  );
  always_comb begin
    channel_write_enable = 1'b1;
    channel_store_value = channel_value;
    // 未知输入按逐条件更新值保存，已知输入采用独立的写入资格。
    case (^{i_state, i_cache_rsp_valid, i_cache_rsp_error, i_wr_valid, i_wr_ready,
            o_chunk_reaches_end, i_row_last_q, i_col_idx, i_active_cols_q, o_chunk_count,
            active_remaining, o_group_end_o_equal, i_q0, i_group_shape_o_valid, i_c.group_c,
            i_current_q_remainder, i_decode_index, i_decode_inner, i_channel_accept_fire,
            committing_tile.channel, o_ch_q, i_ch0, o_group_range_channel[2], next_channel,
            o_incoming_context, i_tile_admission_ready})
      1'b0, 1'b1: begin
        channel_write_enable = i_channel_accept_fire || channel_phase_write;
        channel_store_value = channel_selected_value;
      end
      default: ;
    endcase
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_ch_q <= 16'd0;
    end else if (channel_write_enable) begin
      o_ch_q <= channel_store_value;
    end
  end

  // 配置通道数只作用于低十六位，高位递增与低位求和并行完成。
  assign cfg_next_group_low = {1'b0, i_q0[15:0]} + {1'b0, i_cfg.group_c};
  assign cfg_next_group_high = {1'b0, i_q0[31:16]} + 17'd1;
  assign o_cfg_next_group = {
    cfg_next_group_low[16] ? cfg_next_group_high : {1'b0, i_q0[31:16]},
    cfg_next_group_low[15:0]};
  parallel_prefix_add #(.p_width(33), .p_group_width(8), .p_preserve_groups(1'b1)) u_cfg_skip_group (
    .i_a({1'b0, i_q0}), .i_b({16'd0, i_cfg.group_c, 1'b0}), .i_carry(1'b0),
    .o_sum(o_cfg_skip_group), .o_carry(unused_cfg_skip_carry)
  );

  // Descriptor commit takes priority over advancing the completing stream.
  assign address_stream_write = i_wr_valid && i_wr_ready && !i_tile_commit;
  assign address_column_advance = !o_chunk_reaches_end && !i_past_active_q && o_active_after_chunk;
  assign address_update_select[0] = i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign address_update_select[1] = address_stream_write && o_chunk_reaches_end && !i_row_last_q &&
    i_row_base_valid && !i_geometry_tile;
  assign address_update_select[2] = address_stream_write && address_column_advance &&
    o_group_end_o_equal && i_coordinate_address_valid;
  assign address_update_select[3] = address_stream_write && address_column_advance &&
    !o_group_end_o_equal;
  assign address_update_select[4] = i_state[$clog2(ADDRESS_CHANNEL)];
  if (!p_register_descriptor) begin : g_early_address_data
    logic [31:0] selected_address;
    // 运行阶段提前选择地址，传输接收条件控制寄存器使能。
    always_comb begin
      selected_address = next_byte_addr;
      if (active_select_commit) begin
        selected_address = committing_tile.address;
      end else if (i_state[$clog2(ADDRESS_CHANNEL)]) begin
        selected_address = i_channel_addr;
      end else if (o_chunk_reaches_end) begin
        selected_address = i_next_row_addr;
      end else if (o_group_end_o_equal && i_coordinate_address_valid) begin
        selected_address = i_next_tap_addr;
      end
    end
    // 按位传递保留四态仿真的未知值传播。
    assign address_update_value = selected_address & 32'hffff_ffff;
  end else begin : g_qualified_address_data
    assign address_update_value = ({32{address_update_select[0]}} & committing_tile.address) |
      ({32{address_update_select[1]}} & i_next_row_addr) |
      ({32{address_update_select[2]}} & i_next_tap_addr) |
      ({32{address_update_select[3]}} & next_byte_addr) |
      ({32{address_update_select[4]}} & i_channel_addr);
  end
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) o_addr <= 32'd0;
    else if (|address_update_select) o_addr <= address_update_value;
  end

  if (p_saved_word_range) begin : g_saved_word_range
    logic [4:0][p_word_shift-1:0] source_low;
    logic [p_cache_read_bytes-1:0][4:0] source_available;
    logic [p_cache_read_bytes-1:0] next_available;
    logic [p_cache_read_bytes-1:0] available_write_value;

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
      assign next_available[byte_index] = active_select_commit ? source_available[byte_index][0] :
          i_state[$clog2(ADDRESS_CHANNEL)] ? source_available[byte_index][4] :
          o_chunk_reaches_end ? source_available[byte_index][1] :
          (o_group_end_o_equal && i_coordinate_address_valid) ? source_available[byte_index][2] :
          source_available[byte_index][3];
    end
    if (!p_register_descriptor) begin : g_parallel_descriptor
      logic [13:0] range_select;
      logic [13:0][p_cache_read_bytes-1:0] range_data;
      logic [p_cache_read_bytes-1:0] parallel_available;

      // 描述符地址先分别计算字内范围，完整来源选择只进入末级位归并。
      for (genvar candidate = 0; candidate < 10; candidate++) begin : g_candidate
        assign range_select[candidate] = active_select_commit && committing_tile.operation[candidate];
        for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_byte
          assign range_data[candidate][byte_index] =
              {1'b0, i_incoming_address_candidates[candidate][p_word_shift-1:0]} <
              (p_word_shift+1)'(p_cache_read_bytes-byte_index);
        end
      end
      assign range_select[10] = !active_select_commit && i_state[$clog2(ADDRESS_CHANNEL)];
      assign range_select[11] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          o_chunk_reaches_end;
      assign range_select[12] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          !o_chunk_reaches_end && o_group_end_o_equal && i_coordinate_address_valid;
      assign range_select[13] = !active_select_commit && !i_state[$clog2(ADDRESS_CHANNEL)] &&
          !o_chunk_reaches_end && !(o_group_end_o_equal && i_coordinate_address_valid);
      for (genvar byte_index = 0; byte_index < p_cache_read_bytes; byte_index++) begin : g_live
        assign range_data[10][byte_index] = source_available[byte_index][4];
        assign range_data[11][byte_index] = source_available[byte_index][1];
        assign range_data[12][byte_index] = source_available[byte_index][2];
        assign range_data[13][byte_index] = source_available[byte_index][3];
      end
      onehot_mux #(.p_choices(14), .p_width(p_cache_read_bytes)) u_range (
        .i_select(range_select), .i_data(range_data), .o_data(parallel_available)
      );
`ifdef SYNTHESIS
      assign available_write_value = parallel_available;
`else
      // 未知来源保留按地址比较和优先选择的四态传播。
      always_comb begin
        case (^{active_select_commit, i_state[$clog2(ADDRESS_CHANNEL)],
                o_chunk_reaches_end, o_group_end_o_equal, i_coordinate_address_valid,
                committing_tile.operation, i_incoming_address_candidates, source_available})
          1'b0, 1'b1: available_write_value = parallel_available;
          default: available_write_value = next_available;
        endcase
      end
`endif
    end else begin : g_saved_descriptor
      assign available_write_value = next_available;
    end
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) word_available_q <= '1;
      else if (|address_update_select) word_available_q <= available_write_value;
    end
  end else begin : g_combinational_word_range
    assign word_available_q = '0;
  end

  // 保存字命中标志与地址共用更新事件，比较结果仅经过末端选择。
  assign word_response_write = i_state[$clog2(WAIT_WORD)] && i_wr_valid && i_wr_ready;
  assign word_hit_update_select[0] = p_register_descriptor ? i_state[$clog2(DESCRIPTOR_CHECK)] :
      i_tile_commit && !committing_tile.invalid && committing_tile.fast;
  assign word_hit_update_select[3:1] = address_update_select[3:1];
  assign word_hit_update_select[4] = i_state[$clog2(ADDRESS_MATCH)];
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
  assign active_select_commit = p_register_descriptor ? i_tile_commit :
      i_state[$clog2(IDLE)] ||
      ((i_state[$clog2(WAIT_WORD)] || i_state[$clog2(STREAM)] ||
        i_state[$clog2(ZERO_STREAM)]) && i_wr_last);
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
      if (source == 2 && p_lanes <= 16) begin : g_step
        logic [p_lanes:0] active_allowed, remaining_allowed;
        // 各种传输长度提前计算范围，末通道选择只参与最后归并。
        for (genvar step = 0; step <= p_lanes; step++) begin : g_length
          localparam logic [p_tile_count_w-1:0] p_step = p_tile_count_w'(step);
          localparam logic [p_tile_count_w-1:0] p_lane = p_tile_count_w'(lane);
          localparam logic [p_tile_count_w:0] p_boundary = {1'b0, p_step} + {1'b0, p_lane};
          logic active_before_step, remaining_before_step;
          logic active_after_boundary, remaining_after_boundary;
          if (p_step == '0) begin : g_zero_step
            assign active_before_step = 1'b0;
            assign remaining_before_step = 1'b0;
          end else begin : g_positive_step
            assign active_before_step = active_remaining < p_step;
            assign remaining_before_step = col_remaining < p_step;
          end
          if (&p_boundary[p_tile_count_w-1:0]) begin : g_last_boundary
            assign active_after_boundary = 1'b0;
            assign remaining_after_boundary = 1'b0;
          end else begin : g_lower_boundary
            assign active_after_boundary = active_remaining > p_boundary[p_tile_count_w-1:0];
            assign remaining_after_boundary = col_remaining > p_boundary[p_tile_count_w-1:0];
          end
          // 模减法后的范围直接表示为两个常量边界之间的区间。
          if (p_boundary[p_tile_count_w]) begin : g_wrapped_boundary
            assign active_allowed[step] = active_before_step && active_after_boundary;
            assign remaining_allowed[step] = remaining_before_step && remaining_after_boundary;
          end else begin : g_ordered_boundary
            assign active_allowed[step] = active_before_step || active_after_boundary;
            assign remaining_allowed[step] = remaining_before_step || remaining_after_boundary;
          end
        end
        assign candidate_allowed[source] = |(o_chunk_selected & active_allowed);
        assign column_allowed[source] = |(o_chunk_selected & remaining_allowed);
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

  // 各运行来源先形成目标状态，通道结束条件只选择已经完成的候选。
  conv_im2col_stream_control u_stream_control (
    .i_chunk_end(o_chunk_reaches_end), .i_row_last(i_row_last_q),
    .i_row_base_valid(i_row_base_valid), .i_geometry_tile(i_geometry_tile),
    .i_next_row_padding(i_next_row_padding), .i_next_row_word_hit(next_row_word_hit),
    .i_row_coordinate_valid(i_row_coordinate_valid),
    .i_past_active(i_past_active_q), .i_active_after(o_active_after_chunk),
    .i_group_end(o_group_end_o_equal), .i_coordinate_address_valid(i_coordinate_address_valid),
    .i_next_tap_padding(i_next_tap_padding), .i_next_word_equal(i_next_word_o_equal),
    .i_padding(i_pad_q), .i_tap_context(o_request_tap_context),
    .i_word_boundary(word_boundary), .i_stream_eligible(stream_request_eligible),
    .o_state(stream_static_state), .o_request_selected(stream_request_selected),
    .o_row_selected(stream_row_selected), .o_tap_selected(stream_tap_selected)
  );
  // 接收条件只改变 FETCH 和 WAIT_WORD 两个状态位。
  assign stream_read_accepted = i_cache_req_ready &&
      (stream_request_selected || (stream_row_selected && row_request_eligible));
  for (genvar state_bit = 0; state_bit < $bits(st_t); state_bit++) begin : g_stream_accept_state
    if (state_bit == $clog2(FETCH)) begin : g_fetch
      assign stream_accepted_state[state_bit] = stream_static_state[state_bit] && !stream_read_accepted;
    end else if (state_bit == $clog2(WAIT_WORD)) begin : g_wait
      assign stream_accepted_state[state_bit] = stream_read_accepted;
    end else begin : g_static
      assign stream_accepted_state[state_bit] = stream_static_state[state_bit];
    end
  end
`ifdef SYNTHESIS
  assign o_stream_advance_state = stream_accepted_state;
`else
  always_comb begin
    o_stream_advance_state = stream_static_state;
    if (stream_request_selected && i_cache_req_ready) o_stream_advance_state = WAIT_WORD;
    if (stream_row_selected)
      o_stream_advance_state = row_request_eligible && i_cache_req_ready ? WAIT_WORD : FETCH;
    case (^{stream_static_state, stream_request_selected, stream_row_selected,
            row_request_eligible, i_cache_req_ready})
      1'b0, 1'b1: o_stream_advance_state = stream_accepted_state;
      default: ;
    endcase
  end
`endif

endmodule

// 行、核位置及组内推进分别计算，末级独热选择只接收运行位置条件。
(* keep_hierarchy = "yes" *)
module conv_im2col_stream_control (
  input wire logic i_chunk_end, i_row_last,
  input wire logic i_row_base_valid, i_geometry_tile,
  input wire logic i_next_row_padding, i_next_row_word_hit, i_row_coordinate_valid,
  input wire logic i_past_active, i_active_after, i_group_end,
  input wire logic i_coordinate_address_valid, i_next_tap_padding, i_next_word_equal,
  input wire logic i_padding, i_tap_context, i_word_boundary, i_stream_eligible,
  output conv_im2col_frontend_pkg::st_t o_state,
  output logic o_request_selected, o_row_selected, o_tap_selected
);
  import conv_im2col_frontend_pkg::*;
  st_t row_state, tap_state, column_state;
  logic row_request, tap_request, column_request;
  logic [3:0] source_select;
  logic [3:0][29:0] candidate;
  logic [29:0] selected;

  always_comb begin
    row_state = FETCH;
    row_request = 1'b0;
    if (i_row_last) row_state = IDLE;
    else if (i_row_base_valid && !i_geometry_tile) begin
      if (i_next_row_padding) row_state = ZERO_STREAM;
      else if (i_next_row_word_hit) row_state = STREAM;
      else row_request = 1'b1;
    end else if (i_row_coordinate_valid) row_state = ADDRESS;
    else row_state = COORD;

    tap_state = FETCH;
    tap_request = 1'b0;
    if (i_coordinate_address_valid) begin
      if (i_next_tap_padding) tap_state = ZERO_STREAM;
      else if (i_next_word_equal && !i_padding) tap_state = STREAM;
      else tap_request = i_tap_context;
    end else tap_state = ADDRESS;

    column_state = FETCH;
    column_request = 1'b0;
    if (i_padding) column_state = ZERO_STREAM;
    else if (!i_word_boundary) column_state = STREAM;
    else column_request = i_stream_eligible;
  end
  assign source_select[0] = i_chunk_end;
  assign source_select[1] = !i_chunk_end && (i_past_active || !i_active_after);
  assign source_select[2] = !i_chunk_end && !i_past_active && i_active_after && i_group_end;
  assign source_select[3] = !i_chunk_end && !i_past_active && i_active_after && !i_group_end;
  assign candidate[0] = {1'b0, row_request, 1'b0, row_state};
  assign candidate[1] = {3'b000, ZERO_STREAM};
  assign candidate[2] = {tap_request, 1'b0, tap_request, tap_state};
  assign candidate[3] = {2'b00, column_request, column_state};
  onehot_mux #(.p_choices(4), .p_width(30)) u_state_choice (
    .i_select(source_select), .i_data(candidate), .o_data(selected)
  );
`ifdef SYNTHESIS
  assign {o_tap_selected, o_row_selected, o_request_selected, o_state} = selected;
`else
  always_comb begin
    o_state = FETCH;
    o_request_selected = 1'b0;
    o_row_selected = 1'b0;
    o_tap_selected = 1'b0;
    if (i_chunk_end) begin
      o_state = row_state;
      o_row_selected = row_request;
    end else if (i_past_active || !i_active_after) begin
      o_state = ZERO_STREAM;
    end else if (i_group_end) begin
      o_state = tap_state;
      o_request_selected = tap_request;
      o_tap_selected = tap_request;
    end else begin
      o_state = column_state;
      o_request_selected = column_request;
    end
    case (^{i_chunk_end, i_past_active, i_active_after, i_group_end, candidate})
      1'b0, 1'b1: {o_tap_selected, o_row_selected, o_request_selected, o_state} = selected;
      default: ;
    endcase
  end
`endif
endmodule

// 描述符、当前读取和输出推进并行决定请求资格，末端统一归并。
(* keep_hierarchy = "yes" *)
module conv_im2col_request_control #(
  parameter int p_size = 16,
  parameter int p_rw = $clog2(p_size+1),
  parameter bit p_register_descriptor = 1'b0
) (
  input wire logic i_tile_valid,
  input wire logic i_tile_ready,
  input wire logic i_incoming_fast,
  input wire logic i_incoming_padding,
  input wire logic i_incoming_word_hit,
  input wire logic [p_rw-1:0] i_tile_rows,
  input wire logic [p_rw-1:0] i_tile_cols,
  input wire logic i_tile_q_before_end,
  input wire logic i_tile_rows_in_range,
  input wire logic i_fetch,
  input wire logic i_current_word_hit,
  input wire logic i_wr_valid,
  input wire logic i_wr_ready,
  input wire logic i_stream_request_eligible,
  input wire logic i_row_request_eligible,
  input wire logic i_tap_selected,
  output logic o_cache_req_valid
);
  logic descriptor_request;
  logic fetch_request;
  logic output_request;
  logic descriptor_eligible;

  conv_im2col_descriptor_request #(
    .p_size(p_size), .p_rw(p_rw), .p_register_descriptor(p_register_descriptor)
  ) u_descriptor_request (
    .i_tile_valid(i_tile_valid), .i_tile_ready(i_tile_ready), .i_incoming_fast(i_incoming_fast),
    .i_tile_rows(i_tile_rows), .i_tile_cols(i_tile_cols),
    .i_tile_q_before_end(i_tile_q_before_end), .i_tile_rows_in_range(i_tile_rows_in_range),
    .o_eligible(descriptor_eligible)
  );
  assign descriptor_request = descriptor_eligible && !i_incoming_padding && !i_incoming_word_hit;
  assign fetch_request = i_fetch && !i_current_word_hit;
  assign output_request = i_wr_valid && i_wr_ready &&
      (i_stream_request_eligible || i_row_request_eligible || i_tap_selected);
  assign o_cache_req_valid = descriptor_request || fetch_request || output_request;
endmodule

// 输入掩码先形成各个有效长度，再与已经保存的组末位置匹配。
(* keep_hierarchy = "yes" *)
module conv_im2col_mask_end #(
  parameter int p_lanes = 8,
  parameter bit p_contiguous = 1'b0
) (
  input wire logic [p_lanes-1:0] i_available,
  input wire logic [p_lanes:0] i_boundary,
  output logic o_end
);
  logic [p_lanes:0] selected;
  assign selected[0] = p_contiguous ? !i_available[0] : !(|i_available);
  for (genvar step = 1; step <= p_lanes; step++) begin : g_step
    if (step == p_lanes) begin : g_last
      assign selected[step] = i_available[step-1];
    end else if (p_contiguous) begin : g_contiguous
      assign selected[step] = i_available[step-1] && !i_available[step];
    end else begin : g_general
      assign selected[step] = i_available[step-1] && !(|i_available[p_lanes-1:step]);
    end
  end
  onehot_mux #(.p_choices(p_lanes+1), .p_width(1)) u_boundary (
    .i_select(selected), .i_data(i_boundary), .o_data(o_end)
  );
endmodule

// 输出阶段和数据格式只选择已经完成的三个组末结果。
(* keep_hierarchy = "yes" *)
module conv_im2col_group_end_select (
  input wire logic i_word_output,
  input wire logic i_input_s16,
  input wire logic [2:0] i_end,
  output logic o_end
);
  assign o_end = i_word_output ? (i_input_s16 ? i_end[2] : i_end[1]) : i_end[0];
endmodule

// 描述符形状和接收资格提前归并，命中位直接进入最后的请求选择。
(* keep_hierarchy = "yes" *)
module conv_im2col_descriptor_request #(
  parameter int p_size = 16,
  parameter int p_rw = $clog2(p_size+1),
  parameter bit p_register_descriptor = 1'b0
) (
  input wire logic i_tile_valid, i_tile_ready, i_incoming_fast,
  input wire logic [p_rw-1:0] i_tile_rows, i_tile_cols,
  input wire logic i_tile_q_before_end, i_tile_rows_in_range,
  output logic o_eligible
);
  assign o_eligible = !p_register_descriptor && i_tile_valid && i_tile_ready && i_incoming_fast &&
      i_tile_rows != 0 && 32'(i_tile_rows) <= p_size && 32'(i_tile_cols) <= p_size &&
      i_tile_q_before_end && i_tile_rows_in_range;
endmodule

// 每条通道的末列资格只使用该通道的范围和运行标志。
(* keep_hierarchy = "yes" *)
module conv_im2col_chunk_lane #(
  parameter bit p_narrow_lane = 1'b1
) (
  input wire logic i_narrow_output, i_column_allowed, i_next_column_allowed,
  input wire logic i_past_active, i_group_allowed, i_active_allowed,
  output logic o_end
);
  assign o_end = (!i_narrow_output || p_narrow_lane) && i_column_allowed && !i_next_column_allowed &&
      (i_past_active || (i_group_allowed && i_active_allowed));
endmodule

// 字内覆盖和补零覆盖均提前完成，格式选择保留条件表达式的四态语义。
(* keep_hierarchy = "yes" *)
module conv_im2col_chunk_end_select (
  input wire logic i_first_column_allowed, i_word_output, i_input_s16,
  input wire logic [2:0] i_format_end,
  output logic o_end
);
  logic padding_end;
  assign padding_end = !i_word_output && i_format_end[2];
  assign o_end = !i_first_column_allowed ||
      (i_input_s16 ? (i_format_end[1] || padding_end) : (i_format_end[0] || padding_end));
endmodule

// 三个位的模差和借位只依赖六个原始输入位。
(* keep_hierarchy = "yes" *)
module conv_tile_low_difference (
  input wire logic [2:0] i_a, i_b,
  output logic [2:0] o_difference,
  output logic o_borrow
);
  logic [3:0] borrow;
  assign borrow[0] = 1'b0;
  for (genvar bit_index = 0; bit_index < 3; bit_index++) begin : g_bit
    assign o_difference[bit_index] = i_a[bit_index] ^ i_b[bit_index] ^ borrow[bit_index];
    assign borrow[bit_index+1] = (!i_a[bit_index] && i_b[bit_index]) ||
        (!(i_a[bit_index] ^ i_b[bit_index]) && borrow[bit_index]);
  end
  assign o_borrow = borrow[3];
endmodule

// 两位差值在两种借位条件下分别比较，所有输出均只依赖六个位输入。
(* keep_hierarchy = "yes" *)
module conv_tile_high_compare #(
  parameter bit p_borrow = 1'b0
) (
  input wire logic [1:0] i_a, i_b, i_target,
  output logic o_less, o_equal, o_borrow, o_top
);
  logic [1:0] difference;
  logic [2:0] borrow;
  assign borrow[0] = p_borrow;
  for (genvar bit_index = 0; bit_index < 2; bit_index++) begin : g_bit
    assign difference[bit_index] = i_a[bit_index] ^ i_b[bit_index] ^ borrow[bit_index];
    assign borrow[bit_index+1] = (!i_a[bit_index] && i_b[bit_index]) ||
        (!(i_a[bit_index] ^ i_b[bit_index]) && borrow[bit_index]);
  end
  assign o_less = (!difference[1] && i_target[1]) ||
      (!(difference[1] ^ i_target[1]) && !difference[0] && i_target[0]);
  assign o_equal = !(|(difference ^ i_target));
  assign o_borrow = borrow[2];
  assign o_top = difference[1];
endmodule

// 高段两种关系和低段比较同时就绪，低位借位只决定最终次序。
(* keep_hierarchy = "yes" *)
module conv_tile_low_less_select (
  input wire logic [1:0] i_high_less, i_high_equal,
  input wire logic i_low_borrow, i_low_less,
  output logic o_less
);
  assign o_less = i_low_borrow ?
      (i_high_less[1] || (i_high_equal[1] && i_low_less)) :
      (i_high_less[0] || (i_high_equal[0] && i_low_less));
endmodule

// 默认十六列只检查余量最高位，显式列数由独立的完整低段比较处理。
(* keep_hierarchy = "yes" *)
module conv_tile_low_flag_select (
  input wire logic [1:0] i_high_borrow, i_high_top,
  input wire logic i_low_borrow, i_columns_nonzero,
  output logic o_borrow, o_default_allows
);
  assign o_borrow = i_low_borrow ? i_high_borrow[1] : i_high_borrow[0];
  assign o_default_allows = i_columns_nonzero ||
      (i_low_borrow ? i_high_top[1] : i_high_top[0]);
endmodule

// 五位余量的低三位和高两位并行完成比较，不串接减法结果与宽比较器。
(* keep_hierarchy = "yes" *)
module conv_tile_group_low5 (
  input wire logic [4:0] i_group, i_first, i_columns,
  output logic o_borrow, o_less, o_default_allows
);
  logic [2:0] difference_low;
  logic low_borrow, low_less, unused_low_equal;
  logic [1:0] high_less, high_equal, high_borrow, high_top;
  conv_tile_low_difference u_difference (
    .i_a(i_group[2:0]), .i_b(i_first[2:0]),
    .o_difference(difference_low), .o_borrow(low_borrow)
  );
  parallel_unsigned_compare_leaf #(.p_width(3)) u_low (
    .i_a(difference_low), .i_b(i_columns[2:0]),
    .o_less(low_less), .o_equal(unused_low_equal)
  );
  for (genvar borrow = 0; borrow < 2; borrow++) begin : g_high
    conv_tile_high_compare #(.p_borrow(borrow == 1)) u_compare (
      .i_a(i_group[4:3]), .i_b(i_first[4:3]), .i_target(i_columns[4:3]),
      .o_less(high_less[borrow]), .o_equal(high_equal[borrow]),
      .o_borrow(high_borrow[borrow]), .o_top(high_top[borrow])
    );
  end
  conv_tile_low_less_select u_less (
    .i_high_less(high_less), .i_high_equal(high_equal),
    .i_low_borrow(low_borrow), .i_low_less(low_less), .o_less(o_less)
  );
  conv_tile_low_flag_select u_flags (
    .i_high_borrow(high_borrow), .i_high_top(high_top),
    .i_low_borrow(low_borrow), .i_columns_nonzero(|i_columns),
    .o_borrow(o_borrow), .o_default_allows(o_default_allows)
  );
endmodule

// 高段、低段和默认列数资格均已完成，六个位条件直接给出组范围。
(* keep_hierarchy = "yes" *)
module conv_tile_group_range_result (
  input wire logic i_high_before, i_high_equal, i_high_next_equal,
  input wire logic i_low_borrow, i_low_less, i_default_allows,
  output logic o_fits
);
  assign o_fits =
      (i_high_before && (!i_low_borrow || !i_high_next_equal || (!i_low_less && i_default_allows))) ||
      (i_high_equal && !i_low_borrow && !i_low_less && i_default_allows);
endmodule

// 每组三位同时形成两种进位输入对应的和值。
(* keep_hierarchy = "yes" *)
module conv_im2col_sample_sum_group(
  input wire logic [2:0] i_a, i_b,
  output logic [2:0] o_zero, o_one,
  output logic o_generate, o_propagate
);
  assign o_zero[0] = i_a[0] ^ i_b[0];
  assign o_zero[1] = i_a[1] ^ i_b[1] ^ (i_a[0] & i_b[0]);
  assign o_zero[2] = i_a[2] ^ i_b[2] ^
      ((i_a[1] & i_b[1]) | ((i_a[1] | i_b[1]) & i_a[0] & i_b[0]));
  assign o_one[0] = ~(i_a[0] ^ i_b[0]);
  assign o_one[1] = i_a[1] ^ i_b[1] ^ (i_a[0] | i_b[0]);
  assign o_one[2] = i_a[2] ^ i_b[2] ^
      ((i_a[1] & i_b[1]) | ((i_a[1] | i_b[1]) & (i_a[0] | i_b[0])));
  assign o_generate = (i_a[2] & i_b[2]) |
      ((i_a[2] | i_b[2]) & i_a[1] & i_b[1]) |
      ((i_a[2] | i_b[2]) & (i_a[1] | i_b[1]) & i_a[0] & i_b[0]);
  assign o_propagate = &(i_a | i_b);
endmodule

(* keep_hierarchy = "yes" *)
module conv_im2col_sample_sum_carry(input wire logic i_g0, i_g1, i_p1, output logic o_carry);
  assign o_carry = i_g1 | (i_p1 & i_g0);
endmodule

(* keep_hierarchy = "yes" *)
module conv_im2col_sample_sum_select(input wire logic [2:0] i_zero, i_one,
  input wire logic i_carry, output logic [2:0] o_sum);
  assign o_sum = i_carry ? i_one : i_zero;
endmodule

module conv_im2col_sample_sum(input wire logic [8:0] i_a, i_b,
  output logic [8:0] o_sum);
  logic [2:0][2:0] zero_value, one_value;
  logic [2:0] generate_value, propagate_value;
  logic high_carry;
  for (genvar part=0; part<3; part++) begin:g_part
    conv_im2col_sample_sum_group u_part(.i_a(i_a[3*part+:3]), .i_b(i_b[3*part+:3]),
      .o_zero(zero_value[part]), .o_one(one_value[part]),
      .o_generate(generate_value[part]), .o_propagate(propagate_value[part]));
  end
  conv_im2col_sample_sum_carry u_carry(.i_g0(generate_value[0]), .i_g1(generate_value[1]),
    .i_p1(propagate_value[1]), .o_carry(high_carry));
  assign o_sum[2:0]=zero_value[0];
  conv_im2col_sample_sum_select u_middle(.i_zero(zero_value[1]),.i_one(one_value[1]),
    .i_carry(generate_value[0]),.o_sum(o_sum[5:3]));
  conv_im2col_sample_sum_select u_high(.i_zero(zero_value[2]),.i_one(one_value[2]),
    .i_carry(high_carry),.o_sum(o_sum[8:6]));
endmodule

// 六个输入以内独立归并，较宽向量按相同规则逐层合并。
(* keep_hierarchy = "yes" *)
module conv_im2col_formatter_reduce #(
  parameter int unsigned p_count = 6,
  parameter int unsigned p_width = 1
)(
  input wire logic [p_count-1:0][p_width-1:0] i_data,
  output logic [p_width-1:0] o_data
);
  if (p_count <= 6) begin : g_leaf
    function automatic logic [p_width-1:0] combine(input logic [p_count-1:0][p_width-1:0] values);
      logic [p_width-1:0] result;
      result = '0;
      for (int item = 0; item < p_count; item++) result |= values[item];
      return result;
    endfunction
    assign o_data = combine(i_data);
  end else begin : g_groups
    localparam int p_groups = (p_count+5)/6;
    logic [p_groups-1:0][p_width-1:0] group_value;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_items = p_count-6*group_index < 6 ? p_count-6*group_index : 6;
      conv_im2col_formatter_reduce #(.p_count(p_items), .p_width(p_width)) u_group (
        .i_data(i_data[6*group_index+:p_items]), .o_data(group_value[group_index])
      );
    end
    conv_im2col_formatter_reduce #(.p_count(p_groups), .p_width(p_width)) u_result (
      .i_data(group_value), .o_data(o_data)
    );
  end
endmodule

// 三个完整候选在一组内选择，再按六项归并形成最终数据。
(* keep_hierarchy = "yes" *)
module conv_im2col_formatter_mux #(
  parameter int unsigned p_choices = 8,
  parameter int unsigned p_width = 16
)(
  input wire logic [p_choices-1:0] i_select,
  input wire logic [p_choices-1:0][p_width-1:0] i_data,
  output logic [p_width-1:0] o_data
);
  if (p_choices <= 3) begin : g_leaf
    function automatic logic [p_width-1:0] choose(
      input logic [p_choices-1:0] selected,
      input logic [p_choices-1:0][p_width-1:0] values
    );
      logic [p_width-1:0] result;
      result = '0;
      for (int item = 0; item < p_choices; item++)
        result |= {p_width{selected[item]}} & values[item];
      return result;
    endfunction
    assign o_data = choose(i_select, i_data);
  end else begin : g_groups
    localparam int p_groups = (p_choices+2)/3;
    logic [p_groups-1:0][p_width-1:0] group_value;
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
      localparam int p_items = p_choices-3*group_index < 3 ? p_choices-3*group_index : 3;
      conv_im2col_formatter_mux #(.p_choices(p_items), .p_width(p_width)) u_group (
        .i_select(i_select[3*group_index+:p_items]), .i_data(i_data[3*group_index+:p_items]),
        .o_data(group_value[group_index])
      );
    end
    conv_im2col_formatter_reduce #(.p_count(p_groups), .p_width(p_width)) u_result (
      .i_data(group_value), .o_data(o_data)
    );
  end
endmodule

`default_nettype wire
