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
  localparam int p_saved_group_lanes=p_lanes > 4 && p_lanes <= 8 ? 8 : 4,
  localparam int p_coord_w=35,
  localparam int p_prepared_tile_width=560+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input logic i_clk,
  input logic i_rst_n,
  input logic i_cfg_valid,
  input logic i_cfg_ready,
  input logic i_tile_valid,
  input logic i_tile_ready,
  input logic [31:0] i_tile_p0,
  input logic [31:0] i_tile_q0,
  input logic [p_rw-1:0] i_tile_rows,
  input logic [p_rw-1:0] i_tile_cols,
  input logic [p_slot_w-1:0] i_tile_slot,
  input logic [31:0] i_tile_group,
  input logic i_tile_narrow,
  input logic i_error,
  input conv_im2col_frontend_pkg::st_t i_state,
  input conv_im2col_pkg::conv_cfg_t i_c,
  input logic [31:0] i_reduction_len,
  input logic [31:0] i_position_count,
  input logic [p_row_high_w-1:0] i_position_high_minus_one_q,
  input logic [15:0] i_last_group_channel_q,
  input logic [16:0] i_initial_group_remaining,
  input logic [5:0][p_saved_group_lanes:0] i_group_range_next,
  input logic [31:0] i_p0,
  input logic [31:0] i_q0,
  input logic [31:0] i_tap0,
  input logic [32:0] i_next_group_q,
  input logic [32:0] i_skip_group_q,
  input logic [p_tile_count_w-1:0] i_rows_q,
  input logic [p_tile_count_w-1:0] i_cols_q,
  input logic [15:0] i_ox_q,
  input logic [15:0] i_oy_q,
  input logic [15:0] i_ky0_q,
  input logic [15:0] i_kx0_q,
  input logic [15:0] i_ch0_q,
  input logic [31:0] i_ky0,
  input logic [31:0] i_kx0,
  input logic [31:0] i_ch0,
  input logic signed [p_coord_w-1:0] i_ix,
  input logic signed [p_coord_w-1:0] i_iy,
  input logic [31:0] i_row_group_base,
  input logic [31:0] i_next_row_group_base,
  input logic [31:0] i_addr,
  input logic [p_cache_read_width-1:0] i_word_buf,
  input logic [31:0] i_word_addr,
  input logic i_word_valid,
  input logic i_incoming_word_hit,
  input logic i_descriptor_response_forward,
  input logic [1:0] i_incoming_tile_group_fits,
  input logic [15:0] i_last_output_col_q,
  input logic [15:0] i_last_kernel_col_q,
  input logic [p_cache_read_width-1:0] i_cache_rsp_data,
  input logic i_pred_enabled,
  input logic [31:0] i_groups_q,
  input logic i_geometry_tile,
  input logic i_incoming_tap_wrap,
  input logic [p_coord_w-1:0] i_bound_sum [7],
  input logic [6:0] i_bound_valid,
  input logic signed [32:0] i_row_wrap_dx,
  input logic signed [32:0] i_tap_wrap_dx,
  input logic signed [32:0] i_tap_wrap_pixels,
  input logic [31:0] i_row_step_bytes,
  input logic [31:0] i_tap_step_bytes,
  input logic [31:0] i_row_wrap_bytes,
  input logic [31:0] i_tap_wrap_bytes,
  input logic signed [p_coord_w-1:0] i_tap_pair_dx,
  input logic [31:0] i_tap_pair_pixels,
  input logic [31:0] i_tap_pair_bytes,
  input logic i_row_base_valid,
  input logic i_coordinate_address_valid,
  input logic signed [p_coord_w-1:0] i_row_base_ix,
  input logic signed [p_coord_w-1:0] i_row_base_iy,
  input logic [31:0] i_row_base_pixel,
  input logic [31:0] i_row_base_addr,
  input logic i_row_wrap,
  input logic i_next_row_padding,
  input logic i_row_next_o_equal,
  input logic signed [p_coord_w-1:0] i_next_row_ix,
  input logic signed [p_coord_w-1:0] i_next_row_iy,
  input logic [31:0] i_next_row_pixel,
  input logic [31:0] i_next_row_addr,
  input logic i_tile_ready_context,
  output logic o_tile_rows_in_range,
  output logic o_tile_q_before_end,
  output logic [16:0] o_window_group_remaining_q,
  output logic o_incoming_next_tile_fast,
  output logic o_incoming_next_position_fast,
  output logic o_incoming_skip_tap,
  output logic [15:0] o_window_next_x,
  output logic [15:0] o_window_next_y,
  output logic [15:0] o_window_next_ch,
  output logic o_incoming_fast,
  output logic o_incoming_padding,
  output logic [31:0] o_incoming_ch,
  output logic [31:0] o_incoming_ky,
  output logic [31:0] o_incoming_kx,
  output logic [31:0] o_incoming_addr,
  output logic signed [p_coord_w-1:0] o_incoming_ix,
  output logic signed [p_coord_w-1:0] o_incoming_iy,
  output logic [31:0] o_incoming_pixel,
  output logic o_incoming_word_o_equal,
  output logic o_incoming_live_word_o_equal,
  output logic o_channel_accept_fire,
  output logic [p_prepared_tile_width-1:0] o_committing_tile_packed,
  output logic o_tile_prepared_valid,
  output logic o_tile_commit,
  output logic o_committing_saved_word_hit,
  output logic o_committing_live_word_hit,
  output logic o_descriptor_padding,
  output logic [p_cache_read_width-1:0] o_descriptor_word_data_q,
  output logic [1:0] o_next_row_word_match,
  output logic [1:0] o_incoming_advanced_word_match,
  output logic [15:0] o_kernel_decode_column,
  output logic o_kernel_decode_last
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
  logic [3:0] tile_q_byte_before;
  logic [3:0] tile_q_byte_equal;
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
  logic [31:0] incoming_tap;
  logic signed [p_coord_w-1:0] incoming_step_ix;
  logic signed [p_coord_w-1:0] incoming_wrap_ix;
  logic signed [p_coord_w-1:0] incoming_wrap_iy;
  logic incoming_base_padding;
  logic incoming_step_padding;
  logic incoming_wrap_padding;
  logic [31:0] incoming_pixel_delta;
  logic [31:0] incoming_pixel_next;
  logic [16:0] incoming_pixel_low;
  logic [15:0] incoming_pixel_high_zero;
  logic [15:0] incoming_pixel_high_one;
  logic unused_incoming_pixel_high_zero_carry;
  logic unused_incoming_pixel_high_one_carry;
  logic [5:0] incoming_fast_i_flags;
  logic [1:0] incoming_position_equal;
  logic incoming_q_equal;
  (* keep = 1 *) logic [3:0] incoming_tap_match_o_equal;
  logic [31:0] incoming_tile_match_i_a;
  logic [31:0] incoming_tile_match_i_b;
  logic [31:0] incoming_tile_match_i_target;
  logic incoming_tile_match_i_carry_in;
  logic incoming_tile_match_o_equal;
  logic signed [p_coord_w-1:0] window_forward_ix;
  logic signed [p_coord_w-1:0] window_backward_ix;
  logic signed [p_coord_w-1:0] window_previous_iy;
  logic signed [p_coord_w-1:0] incoming_skip_ix;
  logic signed [p_coord_w-1:0] incoming_skip_iy;
  logic window_forward_padding;
  logic window_backward_padding;
  logic window_previous_padding;
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
  (* keep = p_register_descriptor *) logic prepared_live_word_match;
  logic [8:0] prepared_padding_select;
  logic [8:0] prepared_padding_value;
  (* keep = p_register_descriptor *) logic [9:0] prepared_word_select;
  logic [1:0][31:0] prepared_address;
  logic [31:0] committing_address_delta;
  logic committing_address_carry;
  logic [1:0][31:0] committing_address;
  logic signed [p_coord_w-1:0] prepared_coordinate_x;
  logic signed [p_coord_w-1:0] prepared_coordinate_y;
  logic signed [p_coord_w-1:0] committing_coordinate_dx;
  logic signed [p_coord_w-1:0] committing_coordinate_dy;
  logic [1:0] committing_coordinate_carry;
  logic [1:0][p_coord_w-1:0] committing_coordinate;
  logic [1:0] committing_coordinate_valid;
  logic [31:0] prepared_tap_base;
  logic [31:0] prepared_kernel_x_base;
  logic [31:0] prepared_kernel_y_base;
  logic [31:0] prepared_pixel_base;
  logic signed [2:0] committing_tap_delta;
  logic signed [2:0] committing_kernel_x_delta;
  logic signed [2:0] committing_kernel_y_delta;
  logic [31:0] committing_pixel_delta;
  logic [31:0] committing_kernel_x_base;
  logic [9:0] committing_operation;
  logic committing_pixel_carry;
  logic [31:0] committing_tap;
  logic [31:0] committing_kernel_x;
  logic [31:0] committing_kernel_y;
  logic [31:0] committing_pixel;
  logic [p_tile_count_w-1:0] prepared_columns;
  logic [p_tile_count_w-1:0] prepared_active_columns;
  logic [31:0] descriptor_reduction;
  logic [p_tile_count_w-1:0] descriptor_columns;
  logic [32:0] prepared_next_group;
  logic [32:0] prepared_skip_group;
  logic [32:0] prepared_group_i_a;
  logic [32:0] prepared_group_i_b;
  logic [6:0][1:0][31:0] incoming_address_i_a;
  logic [6:0][1:0][31:0] incoming_address_i_b;
  logic [6:0][1:0][31:0] incoming_address_sum;
  logic [6:0][1:0] unused_incoming_address_carry;
  logic [6:0][1:0] incoming_candidate_word_match;
  logic [1:0] incoming_window_word_match;
  logic [1:0] incoming_skip_word_match;
  logic [4:0][31:0] incoming_pixel_candidate;
  logic [2:0][32:0] incoming_compare_a;
  logic [2:0][32:0] incoming_compare_b;
  logic [2:0][10:0] incoming_part_equal;
  logic [2:0][1:0] incoming_group_equal;
  logic [16:0] negative_group;
  logic [2:0][32:0] target_difference;
  logic [2:0] target_difference_match;
  logic [6:0][p_coord_w-1:0] candidate_coordinate_sum;
  logic [6:0] candidate_coordinate_valid;
  logic incoming_kx_last;
  logic committing_kernel_last;
  logic [15:0] kernel_decode_mask;
  (* keep = 1 *) logic [7:0] kernel_decode_column_equal;
  logic [32:0] next_group_sum;
  logic [32:0] skip_group_sum;
  assign o_committing_tile_packed = committing_tile;
  // 已保存归约位置同时用于组边界和有效列数，结果直接写入运行寄存器。
  assign descriptor_reduction = p_register_descriptor ? prepared_tile_q.reduction : i_tile_q0;
  assign descriptor_columns = p_register_descriptor ? prepared_tile_q.columns : prepared_columns;

  // 描述符的四段范围比较并行进行，最高不同字节决定整体大小关系。
  for (genvar byte_index = 0; byte_index < 4; byte_index++) begin : g_tile_q_range
    assign tile_q_byte_before[byte_index] =
      i_tile_q0[byte_index*8 +: 8] < i_reduction_len[byte_index*8 +: 8];
    assign tile_q_byte_equal[byte_index] =
      i_tile_q0[byte_index*8 +: 8] == i_reduction_len[byte_index*8 +: 8];
  end
  assign o_tile_q_before_end = tile_q_byte_before[3] ||
    (tile_q_byte_equal[3] && tile_q_byte_before[2]) ||
    ((&tile_q_byte_equal[3:2]) && tile_q_byte_before[1]) ||
    ((&tile_q_byte_equal[3:1]) && tile_q_byte_before[0]);

  if (p_rw < 32) begin : g_tile_row_range
    logic [p_row_low_w:0] row_end_low;
    logic high_before_end, high_at_end, high_before_end_by_one, low_within_end;

    // 描述符低位相加与高位比较并行，末端只合并低位进位和边界关系。
    assign row_end_low = {1'b0, i_tile_p0[p_row_low_w-1:0]} + {1'b0, i_tile_rows};
    if (p_row_high_w <= 27) begin : g_high_range_tree
      logic [26:0] row_high_a, row_high_b, row_high_last;
      logic [8:0] leaf_before, leaf_equal, leaf_last_equal;
      logic [2:0] group_before, group_equal;

      // 每三位并行比较，再按高位优先合并各组结果。
      assign row_high_a = 27'(i_tile_p0[31:p_row_low_w]);
      assign row_high_b = 27'(i_position_count[31:p_row_low_w]);
      assign row_high_last = 27'(i_position_high_minus_one_q);
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
      assign high_before_end = i_tile_p0[31:p_row_low_w] < i_position_count[31:p_row_low_w];
      assign high_at_end = i_tile_p0[31:p_row_low_w] == i_position_count[31:p_row_low_w];
      assign high_before_end_by_one = i_tile_p0[31:p_row_low_w] == i_position_high_minus_one_q;
    end
    assign low_within_end = row_end_low[p_row_low_w-1:0] <= i_position_count[p_row_low_w-1:0];
    assign o_tile_rows_in_range =
      (high_before_end && (!row_end_low[p_row_low_w] || !high_before_end_by_one || low_within_end)) ||
      (high_at_end && !row_end_low[p_row_low_w] && low_within_end);
  end else begin : g_tile_row_range_wide
    assign o_tile_rows_in_range = {1'b0, i_tile_p0} + 33'(i_tile_rows) <= {1'b0, i_position_count};
  end

  // 直连描述符在接收周期完成数据字匹配，寄存描述符使用提交后的检查周期。
  if (!p_register_descriptor) begin : g_direct_incoming_word
    logic [31:0] incoming_delta;
    logic [p_word_shift:0] incoming_step_low_sum, incoming_wrap_low_sum;
    logic [31-p_word_shift:0] incoming_word_i_a, incoming_word_i_b, incoming_word_i_target;
    logic [31-p_word_shift:0] incoming_live_word_i_target;
    logic incoming_word_i_carry_in;
    assign incoming_delta = incoming_q_equal ? 32'd0 :
      (i_incoming_tap_wrap ? i_tap_wrap_bytes : i_tap_step_bytes);
    assign incoming_word_i_carry_in = !incoming_q_equal &&
      (i_incoming_tap_wrap ? incoming_wrap_low_sum[p_word_shift] : incoming_step_low_sum[p_word_shift]);
    // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。
    assign incoming_step_low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} + {1'b0, i_tap_step_bytes[p_word_shift-1:0]};
    assign incoming_wrap_low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} + {1'b0, i_tap_wrap_bytes[p_word_shift-1:0]};
    assign incoming_word_i_a = i_row_base_addr[31:p_word_shift];
    assign incoming_word_i_b = incoming_delta[31:p_word_shift];
    assign incoming_word_i_target = i_word_addr[31:p_word_shift];
    add_equal #(.p_width(32-p_word_shift)) u_incoming_word (
      .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_word_i_target),
      .i_carry_in(incoming_word_i_carry_in), .o_equal(o_incoming_word_o_equal)
    );
    // 两个来源的数据字提前完成比较，当前传输的完成条件只选择一位命中结果。
    assign incoming_live_word_i_target = i_addr[31:p_word_shift];
    add_equal #(.p_width(32-p_word_shift)) u_incoming_live_word (
      .i_a(incoming_word_i_a), .i_b(incoming_word_i_b), .i_target(incoming_live_word_i_target),
      .i_carry_in(incoming_word_i_carry_in), .o_equal(o_incoming_live_word_o_equal)
    );
  end else begin : g_prepared_incoming_word
    assign o_incoming_word_o_equal = 1'b0;
    assign o_incoming_live_word_o_equal = 1'b0;
  end

  // 七种地址候选依次为核步进、核换行、跨两个核列、跨核行及列、
  // 已保存窗口的前向、后向、上一核行；两个端口分别计算数据和通道组地址。
  for (genvar candidate = 0; candidate < 7; candidate++) begin : g_incoming_address
    for (genvar base = 0; base < 2; base++) begin : g_base
      assign incoming_address_i_a[candidate][base] = candidate < 4 ?
        (base == 0 ? i_row_base_addr : i_row_group_base) :
        (base == 0 ? window_next_addr : window_next_group_base);
      assign incoming_address_i_b[candidate][base] =
        candidate == 1 ? i_tap_wrap_bytes : candidate == 3 ? i_tap_pair_bytes :
        candidate == 2 ? i_tap_step_bytes << 1 :
        candidate == 5 ? ~i_tap_step_bytes : candidate == 6 ? ~i_tap_pair_bytes : i_tap_step_bytes;
      if (!p_register_descriptor) begin : g_direct_sum
      parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
        .i_a(incoming_address_i_a[candidate][base]), .i_b(incoming_address_i_b[candidate][base]),
        .i_carry((candidate == 5 || candidate == 6)), .o_sum(incoming_address_sum[candidate][base]),
        .o_carry(unused_incoming_address_carry[candidate][base])
      );
      end else begin : g_saved_operands
        assign incoming_address_sum[candidate][base] = '0;
        assign unused_incoming_address_carry[candidate][base] = 1'b0;
      end
    end
    if (!p_register_descriptor) begin : g_direct_word_match
    for (genvar target = 0; target < 2; target++) begin : g_word_match
      logic [p_word_shift:0] low_sum;
      logic [31-p_word_shift:0] high_i_a, high_i_b, high_i_target;
      logic high_i_carry;
      assign low_sum = {1'b0, incoming_address_i_a[candidate][0][p_word_shift-1:0]} +
        {1'b0, incoming_address_i_b[candidate][0][p_word_shift-1:0]} +
        (p_word_shift+1)'((candidate == 5 || candidate == 6));
      assign high_i_a = incoming_address_i_a[candidate][0][31:p_word_shift];
      assign high_i_b = incoming_address_i_b[candidate][0][31:p_word_shift];
      assign high_i_target = target == 0 ? i_word_addr[31:p_word_shift] : i_addr[31:p_word_shift];
      assign high_i_carry = low_sum[p_word_shift];
      add_equal #(.p_width(32-p_word_shift)) u_match (
        .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
        .i_carry_in(high_i_carry), .o_equal(incoming_candidate_word_match[candidate][target])
      );
    end
    end else begin : g_saved_word_match
      assign incoming_candidate_word_match[candidate] = '0;
    end
  end
  for (genvar target = 0; target < 2; target++) begin : g_next_row_match
    logic [31-p_word_shift:0] high_i_target;
    logic [1:0] row_match;
    assign high_i_target = target == 0 ? i_word_addr[31:p_word_shift] : i_addr[31:p_word_shift];
    // 两种行步长先完成字标签比较，行末状态只选择一位匹配结果。
    for (genvar wrap = 0; wrap < 2; wrap++) begin : g_step
      logic [31:0] byte_step;
      logic [p_word_shift:0] low_sum;
      assign byte_step = wrap == 0 ? i_row_step_bytes : i_row_wrap_bytes;
      assign low_sum = {1'b0, i_row_base_addr[p_word_shift-1:0]} +
          {1'b0, byte_step[p_word_shift-1:0]};
      add_equal #(.p_width(32-p_word_shift)) u_match (
        .i_a(i_row_base_addr[31:p_word_shift]), .i_b(byte_step[31:p_word_shift]),
        .i_target(high_i_target), .i_carry_in(low_sum[p_word_shift]), .o_equal(row_match[wrap])
      );
    end
`ifdef SYNTHESIS
    assign o_next_row_word_match[target] = i_row_wrap ? row_match[1] : row_match[0];
`else
    always_comb begin
      case (^{i_row_base_addr, i_row_step_bytes, i_row_wrap_bytes, i_row_wrap, high_i_target})
        1'b0, 1'b1: o_next_row_word_match[target] = i_row_wrap ? row_match[1] : row_match[0];
        default: o_next_row_word_match[target] = i_next_row_addr[31:p_word_shift] == high_i_target;
      endcase
    end
`endif
    assign incoming_window_word_match[target] = incoming_position_previous_row ? incoming_candidate_word_match[6][target] :
      incoming_position_forward_tap ? incoming_candidate_word_match[4][target] :
      incoming_position_backward_tap ? incoming_candidate_word_match[5][target] :
      window_next_addr[31:p_word_shift] == high_i_target;
    assign incoming_skip_word_match[target] = i_kx0_q != 16'd0 ?
      incoming_candidate_word_match[3][target] : incoming_candidate_word_match[2][target];
    assign o_incoming_advanced_word_match[target] = o_incoming_next_position_fast ? incoming_window_word_match[target] :
      o_incoming_next_tile_fast ? o_next_row_word_match[target] : incoming_skip_word_match[target];
  end

  // 像素索引的高十六位分别计算两种输入进位，末端只选择结果。
  assign incoming_pixel_delta = i_incoming_tap_wrap ? 32'($unsigned(i_tap_wrap_pixels)) : {16'd0, i_c.dilation_w};
  assign incoming_pixel_low = {1'b0, i_row_base_pixel[15:0]} + {1'b0, incoming_pixel_delta[15:0]};
  assign {unused_incoming_pixel_high_zero_carry, incoming_pixel_high_zero} =
    {1'b0, i_row_base_pixel[31:16]} + {1'b0, incoming_pixel_delta[31:16]};
  assign {unused_incoming_pixel_high_one_carry, incoming_pixel_high_one} =
    {1'b0, i_row_base_pixel[31:16]} + {1'b0, incoming_pixel_delta[31:16]} + 17'd1;
  assign incoming_pixel_next = {
    incoming_pixel_low[16] ? incoming_pixel_high_one : incoming_pixel_high_zero,
    incoming_pixel_low[15:0]};

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
    assign incoming_group_fits = remaining_wrap ||
      (high_before && (!column_end_low[p_tile_count_w] || !high_next_o_equal || low_within)) ||
      (high_equal && !column_end_low[p_tile_count_w] && low_within);
  end else begin : g_incoming_group_range_wide
    assign incoming_group_fits = 32'(i_cols_q) <= 32'(i_c.group_c) - i_ch0;
  end

  // 地址候选的算术在选择之前并行完成，保留完整三十二位模结果。

  assign incoming_pixel_candidate[0] = window_next_pixel - i_tap_pair_pixels;
  assign incoming_pixel_candidate[1] = window_next_pixel + 32'(i_c.dilation_w);
  assign incoming_pixel_candidate[2] = window_next_pixel - 32'(i_c.dilation_w);
  assign incoming_pixel_candidate[3] = i_row_base_pixel + i_tap_pair_pixels;
  assign incoming_pixel_candidate[4] = i_row_base_pixel + (32'(i_c.dilation_w) << 1);

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
  assign incoming_q_equal = &incoming_group_equal[1];
  // 两个核位置的目标序号随描述符保存，后续接收直接比较目标序号。
  assign incoming_tap_match_o_equal[0] = i_skip_group_q == {1'b0, i_tile_q0};

`ifndef SYNTHESIS
  logic [32:0] reduction_difference;
  assign reduction_difference = {1'b0, i_tile_q0} - {1'b0, window_next_q};
`endif
  // 相邻核位置只需要三种步长的相等条件，各位并行检查完整三十三位进位关系。
  // 配置保存的组末值直接构造负步长，最高位保留跨三十二位边界的区别。
  assign negative_group = {|i_c.group_c, ~i_last_group_channel_q};
  assign target_difference[0] = {17'd0, i_c.group_c};
  assign target_difference[1] = {{16{negative_group[16]}}, negative_group};
  assign target_difference[2] = {{15{negative_group[16]}}, negative_group, 1'b0};
  for (genvar target = 0; target < 3; target++) begin : g_target
    add_equal #(.p_width(33)) u_match (
      .i_a({1'b0, window_next_q}), .i_b(target_difference[target]),
      .i_target({1'b0, i_tile_q0}), .i_carry_in(1'b0),
      .o_equal(target_difference_match[target])
    );
`ifdef SYNTHESIS
    assign incoming_tap_match_o_equal[target+1] = target_difference_match[target];
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
  // 空间分块起点保留三十二位模加结果，溢出行为与描述符地址宽度一致。
  assign incoming_tile_match_i_a = i_p0;
  assign incoming_tile_match_i_b = 32'(i_rows_q);
  assign incoming_tile_match_i_target = i_tile_p0;
  assign incoming_tile_match_i_carry_in = 1'b0;
  add_equal #(.p_width(32)) u_incoming_tile_match (
    .i_a(incoming_tile_match_i_a), .i_b(incoming_tile_match_i_b),
    .i_target(incoming_tile_match_i_target), .i_carry_in(incoming_tile_match_i_carry_in),
    .o_equal(incoming_tile_match_o_equal)
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
  assign incoming_position_same_tap = i_tile_q0 == window_next_q;
  assign incoming_position_forward_tap = window_forward_allowed_q &&
      incoming_tap_match_o_equal[1];
  assign incoming_position_backward_tap = window_backward_allowed_q &&
      incoming_tap_match_o_equal[2];
  // 三列卷积从顶部边缘进入下一输出行时，首个有效核位置向前移动两个位置。
  assign incoming_position_previous_row = window_previous_allowed_q &&
      incoming_tap_match_o_equal[3];
  assign o_incoming_next_position_fast = p_cache_policy == 3 && i_c.windowed && window_next_valid &&
      i_tile_rows == p_rw'(1) && i_tile_p0 == window_next_p &&
      (incoming_position_same_tap || incoming_position_forward_tap ||
       incoming_position_backward_tap || incoming_position_previous_row) &&
      i_incoming_tile_group_fits[0];
  // 连续空间分块继承末行的下一坐标，归约起点变化时继续执行通用解码。
  assign o_incoming_next_tile_fast = p_cache_policy == 3 && i_c.windowed && !i_geometry_tile &&
      i_row_base_valid && i_coordinate_address_valid && i_tile_q0 == i_q0 &&
      incoming_tile_match_o_equal &&
      i_incoming_tile_group_fits[1];
  assign o_incoming_fast = incoming_same_position_fast || o_incoming_next_position_fast || o_incoming_next_tile_fast;

  // 位置递增和保存值的匹配并行计算，更新条件直接使用进位一致性比较。
  assign next_position_i_b = 32'd0;
  assign next_position_i_carry = 1'b1;
  add_equal #(.p_width(32)) u_next_position_match (
    .i_a(i_p0), .i_b(next_position_i_b), .i_target(window_next_p),
    .i_carry_in(next_position_i_carry), .o_equal(next_position_o_equal)
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_next_position (
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
    parallel_prefix_add #(.p_width(p_coord_w), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
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
    assign candidate_coordinate_valid[axis] = high_equal &&
      (low_carry ? high_one_before : high_zero_before);
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
  assign incoming_kx_last = o_incoming_next_position_fast ? incoming_window_kx_last :
    o_incoming_next_tile_fast ? incoming_base_kx_last : o_incoming_skip_tap ? incoming_skip_kx_last :
    !incoming_q_equal ? (i_incoming_tap_wrap ? i_last_kernel_col_q == 16'd0 : incoming_kernel_o_equal[2]) :
    incoming_base_kx_last;

  end else begin : g_saved_kernel_end
    assign incoming_kx_last = 1'b0;
  end

  if (p_register_descriptor) begin : g_commit_kernel_end
    (* keep = 1 *) logic [5:0] kernel_group_equal;
    for (genvar group_index = 0; group_index < 6; group_index++) begin : g_group
      localparam int p_first = group_index * 3;
      localparam int p_width = 16 - p_first < 3 ? 16 - p_first : 3;
      assign kernel_group_equal[group_index] =
          committing_kernel_x[p_first +: p_width] == i_last_kernel_col_q[p_first +: p_width];
    end
    // 末列判断使用已经保存的核坐标，描述符选择不进入等值归并。
    assign committing_kernel_last = &kernel_group_equal;
  end else begin : g_direct_commit_kernel_end
    assign committing_kernel_last = 1'b0;
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
  assign window_forward_padding = !candidate_coordinate_valid[0] ||
    (|window_next_iy[p_coord_w-1:16]) || window_next_iy[15:0] >= i_c.input_h;
  assign window_backward_padding = !candidate_coordinate_valid[1] ||
    (|window_next_iy[p_coord_w-1:16]) || window_next_iy[15:0] >= i_c.input_h;
  assign window_previous_padding = !candidate_coordinate_valid[0] || !candidate_coordinate_valid[2];
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
    o_incoming_padding=incoming_base_padding;
    if (o_incoming_next_position_fast) begin
      incoming_tap=window_next_tap;o_incoming_ch={16'd0,o_window_next_ch};
      o_incoming_kx={16'd0,window_next_kx};o_incoming_ky={16'd0,window_next_ky};
      o_incoming_ix=window_next_ix;o_incoming_iy=window_next_iy;
      o_incoming_pixel=window_next_pixel;o_incoming_addr=window_next_addr;
      incoming_group_base=window_next_group_base;o_incoming_padding=window_shift_padding;
      if (incoming_position_previous_row) begin
        incoming_tap=window_next_tap-32'd2;
        o_incoming_kx=32'd1;o_incoming_ky={16'd0,window_next_ky}-32'd1;
        o_incoming_ix=window_forward_ix;
        o_incoming_iy=window_previous_iy;
        o_incoming_pixel=incoming_pixel_candidate[0];
        o_incoming_addr=incoming_address_sum[6][0];
        incoming_group_base=incoming_address_sum[6][1];
      end else if (incoming_position_forward_tap) begin
        incoming_tap=window_next_tap+32'd1;o_incoming_kx={16'd0,window_next_kx}+32'd1;
        o_incoming_ix=window_forward_ix;
        o_incoming_pixel=incoming_pixel_candidate[1];
        o_incoming_addr=incoming_address_sum[4][0];
        incoming_group_base=incoming_address_sum[4][1];
      end else if (incoming_position_backward_tap) begin
        incoming_tap=window_next_tap-32'd1;o_incoming_kx={16'd0,window_next_kx}-32'd1;
        o_incoming_ix=window_backward_ix;
        o_incoming_pixel=incoming_pixel_candidate[2];
        o_incoming_addr=incoming_address_sum[5][0];
        incoming_group_base=incoming_address_sum[5][1];
      end
    end else if (o_incoming_next_tile_fast) begin
      o_incoming_ix=i_next_row_ix;o_incoming_iy=i_next_row_iy;
      o_incoming_pixel=i_next_row_pixel;o_incoming_addr=i_next_row_addr;
      incoming_group_base=i_next_row_group_base;o_incoming_padding=i_next_row_padding;
    end else if (o_incoming_skip_tap) begin
      incoming_tap=i_tap0+32'd2;
      o_incoming_ix=incoming_skip_ix;o_incoming_iy=incoming_skip_iy;
      o_incoming_padding=incoming_skip_padding;
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
      incoming_tap=i_tap0+1;
      if (i_incoming_tap_wrap) begin
        o_incoming_kx=0;o_incoming_ky=i_ky0+1;
        o_incoming_ix=incoming_wrap_ix;
        o_incoming_iy=incoming_wrap_iy;
        o_incoming_pixel=incoming_pixel_next;
        o_incoming_addr=incoming_address_sum[1][0];incoming_group_base=incoming_address_sum[1][1];
        o_incoming_padding=incoming_wrap_padding;
      end else begin
        o_incoming_kx=i_kx0+1;
        o_incoming_ix=incoming_step_ix;
        o_incoming_pixel=incoming_pixel_next;
        o_incoming_addr=incoming_address_sum[0][0];incoming_group_base=incoming_address_sum[0][1];
        o_incoming_padding=incoming_step_padding;
      end
    end
  end

  // 通道位置先完成流式和解码更新，再选择同周期接收的快速描述符。
  // 描述符准备和状态提交分开保存，候选算术在专用寄存器前完成。
  assign prepared_columns = i_tile_cols == '0 ? p_tile_count_w'(p_size) : p_tile_count_w'(i_tile_cols);
  if (p_tile_count_w < 32) begin : g_prepared_active_columns
    localparam int p_high_width = 32 - p_tile_count_w;
    logic [p_tile_count_w-1:0] distance_low;
    logic [p_high_width-1:0] high_i_a, high_i_b, high_i_target;
    logic high_i_carry, high_o_equal;
    assign distance_low = i_reduction_len[p_tile_count_w-1:0] - descriptor_reduction[p_tile_count_w-1:0];
    assign high_i_carry = i_reduction_len[p_tile_count_w-1:0] < descriptor_reduction[p_tile_count_w-1:0];
    assign high_i_a = descriptor_reduction[31:p_tile_count_w];
    assign high_i_b = '0;
    assign high_i_target = i_reduction_len[31:p_tile_count_w];
    add_equal #(.p_width(p_high_width)) u_distance_high (
      .i_a(high_i_a), .i_b(high_i_b), .i_target(high_i_target),
      .i_carry_in(high_i_carry), .o_equal(high_o_equal)
    );
    assign prepared_active_columns = high_o_equal && distance_low < descriptor_columns ?
      distance_low : descriptor_columns;
  end else begin : g_prepared_active_columns_wide
    assign prepared_active_columns = i_reduction_len - descriptor_reduction < 32'(descriptor_columns) ?
      p_tile_count_w'(i_reduction_len - descriptor_reduction) : descriptor_columns;
  end
  assign prepared_group_i_a = {1'b0, descriptor_reduction};
  assign prepared_group_i_b = {17'd0, i_c.group_c};

  assign next_group_sum = prepared_group_i_a + prepared_group_i_b;
  assign skip_group_sum = prepared_group_i_a + {16'd0, i_c.group_c, 1'b0};
  assign prepared_next_group = next_group_sum;
  assign prepared_skip_group = skip_group_sum;
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
  assign committing_operation = prepared_tile_q.operation;
  always_comb begin
    committing_coordinate_dx = '0;
    committing_coordinate_dy = '0;
    committing_coordinate_carry = '0;
    unique case (1'b1)
      committing_operation[1], committing_operation[7]: begin
        committing_coordinate_dx = p_coord_w'(i_c.dilation_w);
      end
      committing_operation[2]: begin
        committing_coordinate_dx = p_coord_w'(i_tap_wrap_dx);
        committing_coordinate_dy = p_coord_w'(i_c.dilation_h);
      end
      committing_operation[3]: begin
        committing_coordinate_dx = p_coord_w'(i_c.dilation_w) << 1;
      end
      committing_operation[4]: begin
        committing_coordinate_dx = i_tap_pair_dx;
        committing_coordinate_dy = p_coord_w'(i_c.dilation_h);
      end
      committing_operation[5]: begin
        committing_coordinate_dx = prepared_tile_q.row_wrap ? p_coord_w'(i_row_wrap_dx) : p_coord_w'(i_c.stride_w);
        committing_coordinate_dy = prepared_tile_q.row_wrap ? p_coord_w'(i_c.stride_h) : '0;
      end
      committing_operation[8]: begin
        committing_coordinate_dx = ~p_coord_w'(i_c.dilation_w);
        committing_coordinate_carry[0] = 1'b1;
      end
      committing_operation[9]: begin
        committing_coordinate_dx = p_coord_w'(i_c.dilation_w);
        committing_coordinate_dy = ~p_coord_w'(i_c.dilation_h);
        committing_coordinate_carry[1] = 1'b1;
      end
      default: ;
    endcase
  end
  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_coordinate
    logic [p_coord_w-1:0] coordinate_i_a, coordinate_i_b;
    logic coordinate_i_carry;
    assign coordinate_i_a = axis == 0 ? prepared_tile_q.input_x : prepared_tile_q.input_y;
    assign coordinate_i_b = axis == 0 ? committing_coordinate_dx : committing_coordinate_dy;
    assign coordinate_i_carry = committing_coordinate_carry[axis];
    logic [p_coord_w-1:0] coordinate_sum;
    // 完整坐标先进入运行寄存器，范围检查读取下一拍的坐标。
    assign coordinate_sum = coordinate_i_a + coordinate_i_b + p_coord_w'(coordinate_i_carry);
    assign committing_coordinate[axis] = coordinate_sum;
  end
  for (genvar axis = 0; axis < 2; axis++) begin : g_commit_bound
    if (p_register_descriptor) begin : g_saved
      logic unused_equal;
      unsigned_compare #(.p_width(p_coord_w)) u_limit (
        .i_a(axis == 0 ? $unsigned(i_ix) : $unsigned(i_iy)),
        .i_b(p_coord_w'(axis == 0 ? i_c.input_w : i_c.input_h)),
        .o_less(committing_coordinate_valid[axis]), .o_equal(unused_equal)
      );
    end else begin : g_direct
      assign committing_coordinate_valid[axis] = 1'b0;
    end
  end
  // 已保存窗口保留原填充标志，其余描述符统一检查提交坐标的边界。

  assign prepared_padding_value = {window_previous_padding, window_backward_padding,
    window_forward_padding, window_next_padding, i_next_row_padding, incoming_skip_padding,
    incoming_wrap_padding, incoming_step_padding, incoming_base_padding};
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
  end
  // 核位置与像素保存完整起点，提交阶段由操作类型选择任务内固定步长。
  always_comb begin
    prepared_tap_base = i_tap0;
    prepared_kernel_x_base = i_kx0;
    prepared_kernel_y_base = i_ky0;
    prepared_pixel_base = i_row_base_pixel;
    if (o_incoming_next_position_fast) begin
      prepared_tap_base = window_next_tap;
      prepared_kernel_x_base = {16'd0, window_next_kx};
      prepared_kernel_y_base = {16'd0, window_next_ky};
      prepared_pixel_base = window_next_pixel;
    end else if (o_incoming_next_tile_fast) begin
      prepared_pixel_base = i_next_row_pixel;
    end
  end
  always_comb begin
    committing_kernel_x_base = prepared_tile_q.kernel_x;
    committing_tap_delta = 3'sd0;
    committing_kernel_x_delta = 3'sd0;
    committing_kernel_y_delta = 3'sd0;
    committing_pixel_delta = 32'd0;
    committing_pixel_carry = 1'b0;
    unique case (1'b1)
      committing_operation[1]: begin
        committing_tap_delta = 3'sd1;
        committing_kernel_x_delta = 3'sd1;
        committing_pixel_delta = {16'd0, i_c.dilation_w};
      end
      committing_operation[2]: begin
        committing_tap_delta = 3'sd1;
        committing_kernel_x_base = 32'd0;
        committing_kernel_y_delta = 3'sd1;
        committing_pixel_delta = 32'(i_tap_wrap_pixels);
      end
      committing_operation[3]: begin
        committing_tap_delta = 3'sd2;
        committing_kernel_x_base = 32'd0;
        committing_kernel_x_delta = 3'sd2;
        committing_pixel_delta = {16'd0, i_c.dilation_w} << 1;
      end
      committing_operation[4]: begin
        committing_tap_delta = 3'sd2;
        committing_kernel_x_delta = -3'sd1;
        committing_kernel_y_delta = 3'sd1;
        committing_pixel_delta = i_tap_pair_pixels;
      end
      committing_operation[7]: begin
        committing_tap_delta = 3'sd1;
        committing_kernel_x_delta = 3'sd1;
        committing_pixel_delta = {16'd0, i_c.dilation_w};
      end
      committing_operation[8]: begin
        committing_tap_delta = -3'sd1;
        committing_kernel_x_delta = -3'sd1;
        committing_pixel_delta = ~{16'd0, i_c.dilation_w};
        committing_pixel_carry = 1'b1;
      end
      committing_operation[9]: begin
        committing_tap_delta = -3'sd2;
        committing_kernel_x_base = 32'd0;
        committing_kernel_x_delta = 3'sd1;
        committing_kernel_y_delta = -3'sd1;
        committing_pixel_delta = ~i_tap_pair_pixels;
        committing_pixel_carry = 1'b1;
      end
      default: ;
    endcase
  end
  assign committing_tap = prepared_tile_q.tap + 32'($signed(committing_tap_delta));
  assign committing_kernel_x = committing_kernel_x_base + 32'($signed(committing_kernel_x_delta));
  assign committing_kernel_y = prepared_tile_q.kernel_y + 32'($signed(committing_kernel_y_delta));
  assign committing_pixel = prepared_tile_q.pixel + committing_pixel_delta + 32'(committing_pixel_carry);

  // 两个地址共用同一来源，操作类型决定提交时的地址增量。
  always_comb begin
    prepared_address = {i_row_group_base, i_row_base_addr};
    if (o_incoming_next_position_fast)
      prepared_address = {window_next_group_base, window_next_addr};
    else if (o_incoming_next_tile_fast)
      prepared_address = {i_next_row_group_base, i_next_row_addr};
  end
  always_comb begin
    committing_address_delta = '0;
    committing_address_carry = 1'b0;
    unique case (1'b1)
      committing_operation[1], committing_operation[7]: committing_address_delta = i_tap_step_bytes;
      committing_operation[2]: committing_address_delta = i_tap_wrap_bytes;
      committing_operation[3]: committing_address_delta = i_tap_step_bytes << 1;
      committing_operation[4]: committing_address_delta = i_tap_pair_bytes;
      committing_operation[8]: begin
        committing_address_delta = ~i_tap_step_bytes;
        committing_address_carry = 1'b1;
      end
      committing_operation[9]: begin
        committing_address_delta = ~i_tap_pair_bytes;
        committing_address_carry = 1'b1;
      end
      default: ;
    endcase
  end
  for (genvar address_port = 0; address_port < 2; address_port++) begin : g_commit_address
    logic [31:0] address_i_a, address_i_b;
    logic address_i_carry;

    assign address_i_a = address_port == 0 ? prepared_tile_q.address : prepared_tile_q.group_address;
    assign address_i_b = committing_address_delta;
    assign address_i_carry = committing_address_carry;
    logic [31:0] address_sum;
    // 地址求和与数据字匹配分别位于提交和检查周期。
    assign address_sum = address_i_a + address_i_b + 32'(address_i_carry);
    assign committing_address[address_port] = address_sum;
  end
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
    preparing_tile.kernel_x = p_register_descriptor ? prepared_kernel_x_base : o_incoming_kx;
    preparing_tile.kernel_y = p_register_descriptor ? prepared_kernel_y_base : o_incoming_ky;
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
  // 已准备描述符在空闲状态提交，当前分块的完成先经过状态寄存器。
  assign o_tile_commit = p_register_descriptor ?
    (o_tile_prepared_valid && !i_error && i_state[$clog2(IDLE)]) : tile_capture;
  // 检查阶段读取已保存地址，描述符输入队列可以同时保存后续准备项。
  assign o_committing_saved_word_hit = descriptor_saved_word_valid_q && committing_saved_word_match;
  assign o_descriptor_padding = descriptor_padding_select_q ? descriptor_padding_value_q :
      !(&committing_coordinate_valid);
  // 两个数据字标签与运行地址并行比较，命中结果只控制检查阶段的状态。
  for (genvar target = 0; target < 2; target++) begin : g_commit_word_match
    localparam int p_tag_width = 32 - p_word_shift;
    localparam int p_group_count = (p_tag_width + 2) / 3;
    logic [p_tag_width-1:0] target_tag;
    (* keep = p_register_descriptor *) logic [p_group_count-1:0] tag_group_equal;
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
  always_comb begin
    committing_tile = p_register_descriptor ? prepared_tile_q : preparing_tile;
    if (p_register_descriptor) begin
      committing_tile.active_columns = prepared_active_columns;
      committing_tile.next_group = prepared_next_group;
      committing_tile.skip_group = prepared_skip_group;
      committing_tile.address = committing_address[0];
      committing_tile.group_address = committing_address[1];
      committing_tile.input_x = $signed(committing_coordinate[0]);
      committing_tile.input_y = $signed(committing_coordinate[1]);
      committing_tile.kernel_last = committing_kernel_last;
      committing_tile.tap = committing_tap;
      committing_tile.kernel_x = committing_kernel_x;
      committing_tile.kernel_y = committing_kernel_y;
      committing_tile.pixel = committing_pixel;
      committing_tile.padding = 1'b0;
      committing_tile.word_hit = 1'b0;
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

  assign channel_descriptor_valid = i_tile_rows != p_rw'(0) && 32'(i_tile_rows) <= p_size &&
    32'(i_tile_cols) <= p_size && o_tile_q_before_end && o_tile_rows_in_range;
  assign channel_accept_i_flags = {1'b1, o_incoming_fast, channel_descriptor_valid,
                                  i_tile_ready_context, !i_cfg_valid, i_tile_valid};
  assign o_channel_accept_fire = p_register_descriptor ?
    o_tile_commit && !committing_tile.invalid && committing_tile.fast : &channel_accept_i_flags;

endmodule

`default_nettype wire
