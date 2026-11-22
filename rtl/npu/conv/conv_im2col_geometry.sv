// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 配置准备、共享坐标运算和历史位置解码。
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
  localparam int p_saved_group_lanes=p_lanes > 4 && p_lanes <= 8 ? 8 : 4,
  localparam int p_coord_w=35,
  localparam int p_prefetch_count_width=$clog2(p_line_bytes + 2),
  localparam int p_prepared_tile_width=560+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
)(
  input wire logic i_clk,
  input wire logic i_rst_n,
  input wire logic i_cfg_valid,
  input wire logic i_cfg_ready,
  input wire conv_im2col_pkg::conv_cfg_t i_cfg,
  input wire conv_im2col_frontend_pkg::st_t i_state,
  input wire conv_im2col_pkg::conv_cfg_t i_c,
  input wire logic [31:0] i_p0,
  input wire logic [31:0] i_q0,
  input wire logic [31:0] i_tap0,
  input wire logic [15:0] i_ox_q,
  input wire logic [15:0] i_oy_q,
  input wire logic [15:0] i_ky_q,
  input wire logic [15:0] i_kx_q,
  input wire logic [15:0] i_ch_q,
  input wire logic [15:0] i_kx0_q,
  input wire logic [15:0] i_ch0_q,
  input wire logic [31:0] i_ch,
  input wire logic signed [p_coord_w-1:0] i_ix,
  input wire logic signed [p_coord_w-1:0] i_iy,
  input wire logic [31:0] i_pixel_index,
  input wire logic [3:0][31:0] i_coordinate_product_q,
  input wire logic [1:0][32:0] i_coordinate_sum_q,
  input wire logic [31:0] i_channel_product,
  input wire logic [31:0] i_group_base_addr,
  input wire logic [31:0] i_tap_group_base,
  input wire logic [31:0] i_row_group_base,
  input wire logic [31:0] i_addr,
  input wire logic [p_chunk_count_w-1:0] i_chunk_count,
  input wire logic [31:0] i_decode_index,
  input wire logic [31:0] i_decode_outer,
  input wire logic [31:0] i_decode_inner,
  input wire logic i_incoming_next_position_fast,
  input wire logic [15:0] i_window_next_ch,
  input wire logic [15:0] i_request_y_q,
  input wire logic [3:0] i_p_cache_valid,
  input wire logic i_last_p_valid,
  input wire logic [31:0] i_last_p,
  input wire logic i_last_p_overflow_q,
  input wire logic [15:0] i_last_y,
  input wire logic [15:0] i_last_x,
  input wire logic [31:0] i_incoming_pixel,
  input wire logic [3:0] i_prefetch_phase,
  input wire logic [31:0] i_pf_channel_product,
  input wire logic signed [p_coord_w-1:0] i_pfa_y,
  input wire logic [31:0] i_pfa_channel,
  input wire logic [31:0] i_pf0_x,
  input wire logic [31:0] i_pf0_y,
  input wire logic [31:0] i_pf1_pixel,
  input wire logic [31:0] i_pf1_channel,
  input wire logic signed [p_coord_w-1:0] i_request_y,
  input wire logic [1:0] i_address_step_phase,
  input wire logic signed [32:0] i_row_wrap_dx,
  input wire logic signed [32:0] i_tap_wrap_dx,
  input wire logic signed [32:0] i_row_wrap_pixels,
  input wire logic signed [32:0] i_tap_wrap_pixels,
  input wire logic [31:0] i_row_step_bytes,
  input wire logic [31:0] i_tap_step_bytes,
  input wire logic [31:0] i_row_wrap_bytes,
  input wire logic [31:0] i_tap_wrap_bytes,
  input wire logic signed [p_coord_w-1:0] i_row_base_ix,
  input wire logic signed [p_coord_w-1:0] i_row_base_iy,
  input wire logic [31:0] i_row_base_pixel,
  input wire logic [31:0] i_row_base_addr,
  input wire logic i_row_wrap_q,
  input wire logic i_tap_wrap_q,
  input wire logic [p_prepared_tile_width-1:0] i_committing_tile_packed,
  input wire logic i_tile_commit,
  output logic o_cfg_ok,
  output logic o_cfg_basic_valid,
  output logic [1:0] o_cfg_prepare_phase,
  output logic [63:0] o_cfg_input_bytes,
  output logic [63:0] o_cfg_red,
  output logic [31:0] o_cfg_positions,
  output logic [15:0] o_last_group_channel_q,
  output logic [31:0] o_channel_addr,
  output logic [31:0] o_next_row_group_base,
  output logic [2:0] o_decode_end_o_equal,
  output logic o_short_pixel_q,
  output logic [15:0] o_retire_last_row_q,
  output logic [15:0] o_second_last_row_q,
  output logic [15:0] o_last_output_col_q,
  output logic [15:0] o_second_last_col_q,
  output logic [15:0] o_last_kernel_col_q,
  output logic [15:0] o_last_input_col_q,
  output logic o_kernel_width_valid_q,
  output logic [16:0] o_history_limit_low_sum,
  output logic o_p_fast_valid,
  output logic o_p_fast_wrap,
  output logic [31:0] o_p_fast_y,
  output logic [31:0] o_p_fast_x,
  output logic [1:0] o_p_cache_select,
  output logic [31:0] o_request_retire,
  output logic [1:0][31:0] o_retirement_result,
  output logic o_window_index_valid_q,
  output logic [4:0] o_window_index_shift_q,
  output logic [31:0] o_pf_step_base,
  output logic [4:0] o_current_q_div3,
  output logic [15:0] o_current_q_remainder,
  output logic [31:0] o_incoming_req_index,
  output logic [31:0] o_incoming_req_epoch,
  output logic [4:0][31:0] o_epoch_o_sum,
  output logic [31:0] o_stream_channel_full,
  output logic [p_coord_w-1:0] o_bound_sum [7],
  output logic [6:0] o_bound_valid,
  output logic o_next_word_o_equal,
  output logic signed [p_coord_w-1:0] o_tap_pair_dx,
  output logic [31:0] o_tap_pair_pixels,
  output logic [31:0] o_tap_pair_bytes,
  output logic o_row_wrap,
  output logic o_tap_wrap,
  output logic o_next_row_padding,
  output logic o_next_tap_padding,
  output logic o_tap_next_o_equal,
  output logic o_row_next_o_equal,
  output logic signed [p_coord_w-1:0] o_next_row_ix,
  output logic signed [p_coord_w-1:0] o_next_row_iy,
  output logic signed [p_coord_w-1:0] o_next_tap_ix,
  output logic signed [p_coord_w-1:0] o_next_tap_iy,
  output logic [31:0] o_next_row_pixel,
  output logic [31:0] o_next_tap_pixel,
  output logic [31:0] o_next_row_addr,
  output logic [31:0] o_next_tap_addr,
  output logic o_cfg_output_last,
  output logic o_cfg_kernel_last,
  output logic o_cfg_incoming_kernel_last,
  output logic o_group_shape_o_valid,
  output logic o_kernel_shape_o_valid,
  output logic [4:0] o_group_width_shift,
  output logic [4:0] o_kernel_width_shift,
  output logic o_linear_channel_layout_q,
  output logic [5:0] o_k_decode_value,
  output logic [1:0][32:0] o_coordinate_product_sum,
  output logic signed [p_coord_w-1:0] o_coordinate_padded_x,
  output logic signed [p_coord_w-1:0] o_coordinate_padded_y,
  output logic [31:0] o_group_address_sum,
  output logic [31:0] o_prefetch_address_sum,
  output logic [31:0] o_prefetch_pixel_sum,
  output logic [3:0][31:0] o_shared_coordinate_product,
  output logic [1:0][47:0] o_shared_channel_product
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
  logic [16:0] history_limit_i_a;
  logic [16:0] history_limit_i_b;
  logic history_limit_o_less;
  logic unused_history_limit_equal;
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
  logic unused_incoming_epoch_carry;
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
  logic [31-p_word_shift:0] next_word_i_target;
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
  logic unused_history_reduce_high;
  logic [5:0] q_decode_value;
  logic [3:0] q_decode_o_quotient;
  logic [1:0] q_decode_o_remainder;
  logic [31:0] group_channel_sum;
  logic [31:0] prefetch_channel_sum;
  logic [3:0][15:0] coordinate_a;
  logic [3:0][15:0] coordinate_b;
  logic [1:0][31:0] channel_a;
  logic [1:0][15:0] channel_b;
  logic cfg_group_within_input;
  logic cfg_s8_offset_valid;
  logic [p_line_bytes:0] cfg_line_threshold;
  logic [p_line_bytes:0] cfg_line_select;
  logic [31:0] cfg_base_step;
  assign committing_tile = prepared_tile_t'(i_committing_tile_packed);
  // 通道偏移保持十七位范围，完整字节地址使用一次定宽求和。

  assign channel_byte_offset = i_c.input_s16 ? {i_ch_q, 1'b0} : {1'b0, i_ch_q};
  assign channel_address_sum = i_group_base_addr + {15'd0, channel_byte_offset};
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
        .o_sum(o_bound_sum[axis]), .o_valid(o_bound_valid[axis])
      );
    end else begin : g_prepared_coordinate
      assign o_bound_sum[axis] = '0;
      assign o_bound_valid[axis] = 1'b0;
    end
  end

  // 数据字匹配比较读取范围以外的高位，字内偏移单独提供进位。
  assign next_word_i_target = i_addr[31:p_word_shift];
  assign o_next_word_o_equal = o_next_tap_addr[31:p_word_shift] == next_word_i_target;

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
  for (genvar source = 0; source < 5; source++) begin : g_movement_sum
    logic [31:0] movement_sum;
    logic unused_movement_carry;
    // 行边界与卷积核边界共用固定配置步长，分组前缀并行提供完整进位。
    parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
      .i_a(movement_i_a[source]), .i_b(movement_i_b[source]), .i_carry(1'b0),
      .o_sum(movement_sum), .o_carry(unused_movement_carry)
    );
`ifdef SYNTHESIS
    assign movement_o_sum[source] = movement_sum;
`else
    always_comb begin
      case (^{movement_i_a[source], movement_i_b[source]})
        1'b0, 1'b1: movement_o_sum[source] = movement_sum;
        default: movement_o_sum[source] = movement_i_a[source] + movement_i_b[source];
      endcase
    end
`endif
  end

  // Configuration-time products leave only additions and bounds checks at
  // row and tap boundaries while the current word is being transferred.
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
      o_linear_channel_layout_q <= 1'b0;
    end else if (i_cfg_valid && i_cfg_ready) begin
      o_group_shape_o_valid <= group_shape_check_o_valid;
      o_kernel_shape_o_valid <= kernel_shape_check_o_valid;
      output_shape_o_valid <= output_shape_check_o_valid;
      output_width_shift <= power_shift({16'd0,i_cfg.output_w});
      o_group_width_shift <= power_shift({16'd0,i_cfg.group_c});
      o_kernel_width_shift <= power_shift({16'd0,i_cfg.kernel_w});
      o_linear_channel_layout_q <= i_cfg.group_c == i_cfg.input_c &&
          i_cfg.group_offset == 16'd0 && i_cfg.dilation_w == 16'd1;
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
      if (o_cfg_prepare_phase == 2'd1) begin
        retire_bias_q <= {1'b0, i_c.pad_top} +
          (o_short_pixel_q ? (17'd1 << retire_shift_q) : 17'd0);
        // 准备期间复用最终阈值寄存器，先保存低位及高位范围分类。
        retire_compare_q <= retire_scaled_last[15:0];
        retire_all_bounded_q <= !(|retire_scaled_last[30:16]);
        retire_no_bound_q <= |retire_scaled_last[30:17];
      end
      if (o_cfg_prepare_phase == 2'd2) begin
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
    else prefetch_retire_pfa_q <= i_prefetch_phase == 4'd2;
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
  if (p_register_descriptor && p_register_cache_request) begin : g_saved_position_lookup
    logic [1:0] lookup_index;
    logic [63:0] lookup_data;
    logic lookup_hit;
    logic hit_q;
    logic [31:0] coordinates_q;

    // 描述符提交时读取历史项，命中判断和坐标在执行解码前共同保存。
    assign lookup_index = 2'(committing_tile.position >> p_cw);
    assign lookup_data = p_cache_data[lookup_index];
    assign lookup_hit = i_p_cache_valid[lookup_index] &&
        lookup_data[63:32] == committing_tile.position;
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
  end else begin : g_current_position_lookup
    logic [31:0] lookup_key;
    assign {lookup_key, p_cache_y, p_cache_x} = p_cache_data[o_p_cache_select];
    assign p_cache_hit = i_p_cache_valid[o_p_cache_select] && lookup_key == p_decode;
  end
  assign p_cache_write_enable = i_rst_n &&
      ((i_state[$clog2(P_DECODE)] && o_p_fast_valid) ||
       (i_state[$clog2(P_WAIT)] && i_decode_index == i_p0));
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
  // 接收位置与历史位置的差值先保存，坐标解码只执行一次分组加法。
  // 位置差在描述符提交时保存；历史位置更新为当前位置时，差值同时归零。
  assign history_delta_full = {1'b0, committing_tile.position} - {1'b0, i_last_p};
  assign o_history_limit_low_sum = {1'b0, i_p0[15:0]} + {1'b0, i_c.output_w};
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
  assign p_delta = p_register_descriptor ? p_history_delta_q[15:0] : 16'(p_decode - i_last_p);
  parallel_prefix_add #(.p_width(17), .p_group_width(4), .p_preserve_groups(1'b1)) u_history_sum (
    .i_a({1'b0, i_last_x}), .i_b({1'b0, p_delta}), .i_carry(1'b0),
    .o_sum(p_sum), .o_carry(unused_p_sum_carry)
  );

  // 历史列、位置增量和输出宽度先压缩，减法不再依赖前一级完整和值。
  assign history_reduce_i_a = {2'b0, i_last_x} ^ {2'b0, p_delta} ^ ~{2'b0, i_c.output_w};
  assign history_reduce_generate = ({2'b0, i_last_x} & {2'b0, p_delta}) |
    (({2'b0, i_last_x} | {2'b0, p_delta}) & ~{2'b0, i_c.output_w});
  assign {unused_history_reduce_high, history_reduce_i_b} = {history_reduce_generate, 1'b1};
  assign history_reduce_full_sum = {1'b0, history_reduce_i_a} + {1'b0, history_reduce_i_b};
  assign {unused_p_sum_reduced_carry, history_reduce_o_sum} = history_reduce_full_sum;
  assign p_sum_reduced = history_reduce_o_sum[16:0];
  assign history_width_reached = !history_reduce_o_sum[17];
  // 已保存的位置差与历史列数直接组成行尾等式，逐位比较和坐标求和并行。
  assign p_sum_wrap_i_a = i_last_x;
  assign p_sum_wrap_i_b = p_history_delta_q[15:0];
  assign unused_p_sum_wrap_carry = 1'b0;
  assign p_sum_wrap_i_target = p_wrap_target_q;
  assign p_sum_wrap_i_carry_in = 1'b0;
  add_equal #(.p_width(16)) u_p_sum_wrap (
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
  add_equal #(.p_width(16)) u_p_sum_last (
    .i_a(p_sum_last_i_a), .i_b(p_sum_last_i_b), .i_target(p_sum_last_i_target),
    .i_carry_in(p_sum_last_i_carry_in), .o_equal(p_sum_last_o_equal)
  );
  always_comb begin
    o_p_fast_valid=0;o_p_fast_y=0;o_p_fast_x=0;
    o_p_fast_wrap = i_c.output_w != 16'd0 && o_last_output_col_q == 16'd0;
    if (p_decode==0) o_p_fast_valid=1;
    else if (output_shape_o_valid) begin
      // 二次幂输出宽度通过移位和掩码直接得到行列坐标。
      o_p_fast_valid=1;o_p_fast_y=p_decode>>output_width_shift;
      o_p_fast_x=p_decode&{16'd0,o_last_output_col_q};
      o_p_fast_wrap=o_p_fast_x=={16'd0,o_last_output_col_q};
    end
    else if (p_cache_hit) begin
      o_p_fast_valid=1;o_p_fast_y=32'(p_cache_y);o_p_fast_x=32'(p_cache_x);
      o_p_fast_wrap = i_c.output_w != 16'd0 && p_cache_x == o_last_output_col_q;
    end else if (history_range_valid) begin
      o_p_fast_valid=1;o_p_fast_y=32'(i_last_y);o_p_fast_x=32'(p_sum);
      // 模和值等于目标时，历史列数与目标的关系直接给出最高位进位。
      o_p_fast_wrap = i_c.output_w != 16'd0 &&
        ((p_sum_last_o_equal && i_last_x <= p_sum_last_i_target) ||
         (p_sum_wrap_o_equal && (!o_last_output_col_q[15] || i_last_x > p_sum_wrap_i_target)));
      if (history_width_reached) begin o_p_fast_x=32'(p_sum_reduced);o_p_fast_y=32'(i_last_y)+1;end
    end
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
    if (i_cfg_valid && i_cfg_ready) begin
      coordinate_a[0] = i_cfg.input_h;
      coordinate_b[0] = i_cfg.input_w;
      coordinate_a[1] = i_cfg.kernel_h;
      coordinate_b[1] = i_cfg.kernel_w;
      coordinate_a[2] = i_cfg.output_h;
      coordinate_b[2] = i_cfg.output_w;
      coordinate_a[3] = i_cfg.stride_h;
      coordinate_b[3] = i_cfg.input_w;
    end else if (o_cfg_prepare_phase == 2'd1) begin
      coordinate_a[0] = i_c.output_w;
      coordinate_b[0] = i_c.stride_w;
      coordinate_a[1] = i_c.kernel_w;
      coordinate_b[1] = i_c.dilation_w;
      coordinate_a[2] = i_c.dilation_h;
      coordinate_b[2] = i_c.input_w;
      coordinate_a[3] = i_c.stride_w;
      coordinate_b[3] = i_c.input_c;
    end else if (o_cfg_prepare_phase == 2'd2) begin
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
    if (o_cfg_prepare_phase == 2'd1) begin
      channel_a[0] = cfg_input_hw;
      channel_a[1] = cfg_kernel_taps;
      channel_b[1] = i_c.group_c;
    end else if (i_address_step_phase == 2'd1) begin
      channel_a[0] = i_row_wrap_pixels[31:0];
      channel_a[1] = i_tap_wrap_pixels[31:0];
    end else if (i_prefetch_phase == 4'd4) begin
      channel_a[1] = i_pf0_y;
      channel_b[1] = i_c.input_w;
    end
  end
  for (genvar product = 0; product < 2; product++) begin : g_channel
    assign o_shared_channel_product[product] =
        48'(channel_a[product]) * 48'(channel_b[product]);
  end

  assign o_coordinate_product_sum[0] = {1'b0, i_coordinate_product_q[0]} + {1'b0, i_coordinate_product_q[2]};
  assign o_coordinate_product_sum[1] = {1'b0, i_coordinate_product_q[1]} + {1'b0, i_coordinate_product_q[3]};
  assign o_coordinate_padded_x = $signed(p_coord_w'(i_coordinate_sum_q[0])) - $signed(p_coord_w'(i_c.pad_left));
  assign o_coordinate_padded_y = $signed(p_coord_w'(i_coordinate_sum_q[1])) - $signed(p_coord_w'(i_c.pad_top));
  assign group_channel_sum = i_channel_product + 32'(i_c.group_offset);
  assign o_group_address_sum = i_c.input_base + (group_channel_sum << i_c.input_s16);
  assign prefetch_channel_sum = i_pf_channel_product + i_pf1_channel;
  assign o_prefetch_address_sum = i_c.input_base + (prefetch_channel_sum << i_c.input_s16);
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

  // 三项通道数量先逐位压缩，再形成完整十八位求和结果的范围条件。

  assign cfg_group_within_input =
      17'(i_cfg.group_offset) + 17'(i_cfg.group_c) <= 17'(i_cfg.input_c);
  assign cfg_s8_offset_valid = $signed(i_cfg.input_offset) >= -127 && $signed(i_cfg.input_offset) <= 128;

  // 配置乘积经过寄存器后检查溢出。
  always_comb begin
    o_cfg_basic_valid=i_cfg.input_h!=0 && i_cfg.input_w!=0 && i_cfg.input_c!=0 &&
      i_cfg.group_c!=0 && i_cfg.kernel_h!=0 && i_cfg.kernel_w!=0 &&
      i_cfg.output_h!=0 && i_cfg.output_w!=0 && i_cfg.stride_h!=0 && i_cfg.stride_w!=0 &&
      i_cfg.dilation_h!=0 && i_cfg.dilation_w!=0 &&
      cfg_group_within_input;
    if (i_cfg.input_s16) o_cfg_basic_valid=o_cfg_basic_valid && i_cfg.input_offset==0 && !i_cfg.input_base[0];
    else o_cfg_basic_valid=o_cfg_basic_valid && cfg_s8_offset_valid;
    o_cfg_input_bytes={15'd0,cfg_tensor_product};
    o_cfg_red={16'd0,cfg_reduction_product};
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
      2: o_cfg_prepare_phase <= 0;
      default: ;
    endcase
  end
  always_ff @(posedge i_clk) begin
    if (!i_rst_n) begin
    end else if (i_cfg_valid && i_cfg_ready) begin
      cfg_input_hw <= o_shared_coordinate_product[0];
      cfg_kernel_taps <= o_shared_coordinate_product[1];
      cfg_position_product <= o_shared_coordinate_product[2];
    end else case (o_cfg_prepare_phase)
      1: begin
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
    end else if (o_cfg_prepare_phase == 2'd1) begin
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
      o_last_input_col_q <= 16'hffff;

      o_last_group_channel_q <= 16'hffff;

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
      o_last_input_col_q <= i_cfg.input_w - 16'd1;

      o_last_group_channel_q <= i_cfg.group_c - 16'd1;

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
    if (candidate == 3 && p_lanes <= 8) begin : g_stream_shared
      logic [17:0] channel_sum;

      // 通道起点、组内偏移和本拍数量共用一组进位保存加法。
      // 两个十六位操作数和至多八个通道的数量需要十八位结果。
      assign channel_sum = epoch_i_a[candidate][17:0] + epoch_i_b[candidate][17:0];
      assign o_epoch_o_sum[candidate] = {14'd0, channel_sum};
      assign unused_epoch_carry[candidate] = 1'b0;
    end else begin : g_general
      parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_sum (
        .i_a(epoch_i_a[candidate]), .i_b(epoch_i_b[candidate]), .i_carry(epoch_i_carry),
        .o_sum(o_epoch_o_sum[candidate]), .o_carry(unused_epoch_carry[candidate])
      );
    end
  end
  assign stream_channel_i_a = i_ch;
  assign stream_channel_i_b = 32'(i_chunk_count);
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_stream_channel (
    .i_a(stream_channel_i_a), .i_b(stream_channel_i_b), .i_carry(epoch_i_carry),
    .o_sum(o_stream_channel_full), .o_carry(unused_stream_channel_carry)
  );

  // 当前项与新描述符分别完成索引移位和纪元运算，描述符有效条件只控制末级选择。
  assign unused_incoming_epoch_carry = 1'b0;
  assign incoming_epoch_channel = i_incoming_next_position_fast ? o_epoch_o_sum[0] : o_epoch_o_sum[1];
  assign o_incoming_req_index = o_short_pixel_q ? i_incoming_pixel >> o_window_index_shift_q : i_incoming_pixel;
  assign o_incoming_req_epoch = o_short_pixel_q ? 32'd0 :
    (incoming_epoch_channel << i_c.input_s16) >> $clog2(p_line_bytes);

endmodule

`default_nettype wire
