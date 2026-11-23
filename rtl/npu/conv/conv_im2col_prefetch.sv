// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 预取上下文在已有阶段内推进，保存地址、坐标和请求元数据。
module conv_im2col_prefetch #(
  parameter int p_size=16,
  parameter int p_line_bytes=16,
  parameter bit p_register_cache_request=1'b1,
  parameter int p_rw=$clog2(p_size+1),
  localparam int p_tile_count_w=$clog2(p_size+1),
  localparam int p_coord_w=35
)(
  input wire logic i_clk,
  input wire logic i_rst_n,
  input wire logic i_cfg_valid,
  input wire logic i_cfg_ready,
  input wire logic [p_rw-1:0] i_tile_rows,
  input wire logic [p_rw-1:0] i_tile_cols,
  input wire conv_im2col_pkg::conv_cfg_t i_c,
  input wire logic [p_tile_count_w-1:0] i_rows_q,
  input wire logic [p_tile_count_w-1:0] i_cols_q,
  input wire logic [15:0] i_ky_q,
  input wire logic [15:0] i_ky0_q,
  input wire logic [31:0] i_ox,
  input wire logic [31:0] i_oy,
  input wire logic [31:0] i_kx,
  input wire logic [31:0] i_ch,
  input wire logic [31:0] i_kx0,
  input wire logic [31:0] i_ch0,
  input wire logic signed [p_coord_w-1:0] i_ix,
  input wire logic signed [p_coord_w-1:0] i_iy,
  input wire logic i_stream_next_request,
  input wire logic i_next_row_request,
  input wire logic i_incoming_context,
  input wire logic i_incoming_next_tile_fast,
  input wire logic i_incoming_next_position_fast,
  input wire logic [15:0] i_window_next_x,
  input wire logic i_cache_port_valid,
  input wire logic [31:0] i_cache_req_addr,
  input wire logic i_cache_port_ready,
  input wire logic [31:0] i_request_addr_q,
  input wire logic [31:0] i_request_index_q,
  input wire logic [31:0] i_request_epoch_q,
  input wire logic i_short_pixel_q,
  input wire logic [15:0] i_retire_last_row_q,
  input wire logic [15:0] i_second_last_row_q,
  input wire logic [15:0] i_last_output_col_q,
  input wire logic [15:0] i_second_last_col_q,
  input wire logic i_request_index_valid_q,
  input wire logic [31:0] i_incoming_ch,
  input wire logic [31:0] i_incoming_ky,
  input wire logic [31:0] i_incoming_kx,
  input wire logic signed [p_coord_w-1:0] i_incoming_ix,
  input wire logic [31:0] i_req_index,
  input wire logic [31:0] i_req_epoch,
  input wire logic [1:0][31:0] i_retirement_result,
  input wire logic i_req_index_valid,
  input wire logic [4:0] i_window_index_shift_q,
  input wire logic [31:0] i_pf_step_base,
  input wire logic i_fragment_image_fits,
  input wire logic signed [p_coord_w-1:0] i_request_y,
  input wire logic [31:0] i_request_output_y,
  input wire logic [4:0][31:0] i_epoch_o_sum,
  input wire logic [31:0] i_stream_channel_full,
  input wire logic signed [32:0] i_row_pair_dx,
  input wire logic signed [32:0] i_row_wrap_dx,
  input wire logic signed [32:0] i_tap_wrap_dx,
  input wire logic i_row_wrap,
  input wire logic signed [p_coord_w-1:0] i_next_row_ix,
  input wire logic [31:0] i_prefetch_address_sum,
  input wire logic [31:0] i_prefetch_byte_offset,
  input wire logic [31:0] i_prefetch_pixel_sum,
  input wire logic [1:0][47:0] i_shared_channel_product,
  output logic o_pf_valid,
  output logic [31:0] o_pf_addr,
  output logic [31:0] o_pf_index,
  output logic [31:0] o_pf_epoch,
  output logic o_pf_index_valid,
  output logic [3:0] o_prefetch_phase,
  output logic [31:0] o_pf_address_term,
  output logic signed [p_coord_w-1:0] o_pfa_y,
  output logic [31:0] o_pfa_channel,
  output logic [31:0] o_pf0_x,
  output logic [31:0] o_pf0_y,
  output logic [31:0] o_pf1_pixel,
  output logic [31:0] o_pf1_channel,
  output logic [31:0] o_pf1_retire,
  output logic [31:0] o_pf1_ref_addr,
  output logic [31:0] o_pf1_ref_index,
  output logic [31:0] o_pf1_ref_epoch,
  output logic [31:0] o_pf1_ref_retire,
  output logic o_pf1_ref_index_valid,
  output logic o_pf1_fragment,
  output logic o_pf1_coordinate_valid
);
  import conv_im2col_pkg::*;
  import conv_im2col_frontend_pkg::*;
  logic [31:0] pf_distance_q;
  logic [31:0] pf_step_q;
  logic [31:0] pf_address_calc;
  logic pf_offer_valid;
  logic [31:0] pfa_origin_channel;
  logic [31:0] pfa_kernel_x;
  logic [15:0] pfa_kernel_y;
  logic pf_stream_lookahead;
  logic [31:0] pf_x;
  logic [31:0] pf_y;
  logic [31:0] pf_channel;
  logic [31:0] pf_distance;
  logic signed [16:0] pf_y_delta_q;
  logic signed [17:0] pf_y_wrap_delta_q;
  logic [31:0] pf_y_base_q;
  logic [31:0] pf_y_wrapped_q;
  logic [31:0] pf_kernel_advance_q;
  logic [2:0][31:0] pf_prepare_i_a;
  logic [2:0][31:0] pf_prepare_i_b;
  logic [2:0][31:0] pf_prepare_o_sum;
  logic pf_prepare_i_carry;
  logic [2:0] unused_pf_prepare_carry;
  logic signed [16:0] pf_y_delta;
  logic signed [17:0] pf_y_wrap_delta;
  logic unit_row_lookahead;
  logic [15:0] pf_y_step;
  logic pf_coordinate_valid;
  logic pf_next_fragment;
  logic signed [p_coord_w-1:0] pf_wrap_x;
  logic pf_window_ahead;
  logic pf_window_ahead_q;
  logic pf_window_row_valid_q;
  logic pf_ahead_two;
  logic pf_wrap_once;
  logic pf_wrap_twice;
  logic signed [32:0] pf_window_dx_q;
  logic signed [32:0] pf_fragment_dx_q;
  logic [32:0] fragment_distance;
  logic [32:0] fragment_xor;
  logic [32:0] fragment_carry;
  logic signed [32:0] fragment_delta;
  logic [16:0] pf_window_dy_q;
  logic signed [p_coord_w-1:0] pf_window_x;
  logic signed [p_coord_w-1:0] pf_window_y;
  logic signed [p_coord_w-1:0] pf_horizontal_sum;
  logic signed [p_coord_w-1:0] pf_horizontal_delta;
  logic [31:0] prefetch_next_x;
  logic [31:0] prefetch_wrapped_x;
  logic [31:0] prefetch_wrap_base;
  logic [31:0] prefetch_wrap_base_q;
  logic [31:0] prefetch_wrap_i_a;
  logic [31:0] prefetch_wrap_i_b;
  logic [2:0] prefetch_x_carry;
  logic [2:0] unused_prefetch_x_carry;
  logic [2:0][15:0] prefetch_range_a;
  logic [2:0][15:0] prefetch_range_b;
  logic [2:0][15:0] unused_prefetch_range_sum;
  logic [1:0] prefetch_high_zero;
  logic prefetch_next_high_zero;
  logic prefetch_base_no_borrow_q;
  logic pf_crosses_row;
  logic [p_coord_w-1:0] prefetch_horizontal_sum;
  logic unused_prefetch_horizontal_carry;
  logic signed [32:0] pf_window_dx_next;
  logic prefetch_horizontal_low_carry;
  logic prefetch_horizontal_low_carry_q;
  logic [15:0] unused_prefetch_horizontal_prepare_sum;
  logic unused_prefetch_horizontal_low_carry;

  // 同一预取只保存一份引用上下文，各阶段共用其地址和元数据。
  typedef struct packed {
    logic [31:0] address, index, epoch;
    logic index_valid;
  } prefetch_reference_t;
  prefetch_reference_t reference_q;
  logic [31:0] channel_q [2];
  logic [31:0] reference_retire_q;
  logic fragment_q;
  logic coordinate_valid_q;
  logic signed [p_coord_w-1:0] accepted_coordinate_q [2];
  logic [31:0] projected_coordinate_q [2];
  logic [31:0] output_coordinate_q [2];
  logic [31:0] tile_extent_q [2];
  assign o_pf0_x = projected_coordinate_q[0];
  assign o_pf0_y = projected_coordinate_q[1];
  assign o_pf1_channel = channel_q[1];
  assign o_pf1_coordinate_valid = coordinate_valid_q;
  assign o_pf1_fragment = fragment_q;
  assign o_pf1_ref_addr = reference_q.address;
  assign o_pf1_ref_epoch = reference_q.epoch;
  assign o_pf1_ref_index = reference_q.index;
  assign o_pf1_ref_index_valid = reference_q.index_valid;
  assign o_pf1_ref_retire = reference_retire_q;
  assign o_pfa_channel = channel_q[0];
  assign o_pfa_y = accepted_coordinate_q[1];

  // 预读上下文在第一阶段准备纵向增量，第二阶段并行保存两种行坐标。
  // 横向增量先保存低位进位，再与纵向结果共同组成预取坐标。
  assign pf_y_step = pf_stream_lookahead || i_c.kernel_h == 16'd1 ? i_c.stride_h : i_c.dilation_h;
  assign unit_row_lookahead = pf_stream_lookahead && i_c.stride_h == 16'd1 && i_c.dilation_h == 16'd1;
  assign pf_y_delta = unit_row_lookahead ?
    $signed({1'b0, i_c.kernel_h}) - 17'sd1 - $signed({1'b0, pfa_kernel_y}) : 17'sd0;
  assign pf_y_wrap_delta = unit_row_lookahead ?
      $signed({2'b0, i_c.kernel_h}) - $signed({2'b0, pfa_kernel_y}) :
      $signed({2'b0, pf_y_step});
  assign pf_prepare_i_a = {pfa_kernel_x, 32'(accepted_coordinate_q[1]), 32'(accepted_coordinate_q[1])};
  assign pf_prepare_i_b = {pf_distance_q, 32'(pf_y_wrap_delta_q), 32'(pf_y_delta_q)};
  assign pf_prepare_i_carry = 1'b0;
  for (genvar source = 0; source < 3; source++) begin : g_prefetch_prepare
    parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_sum (
      .i_a(pf_prepare_i_a[source]), .i_b(pf_prepare_i_b[source]), .i_carry(pf_prepare_i_carry),
      .o_sum(pf_prepare_o_sum[source]), .o_carry(unused_pf_prepare_carry[source])
    );
  end

  // 两种横坐标并行计算，跨行起点在第一准备周期保存。

  assign prefetch_wrap_i_a = 32'(accepted_coordinate_q[0]);
  assign prefetch_wrap_i_b = ~{16'd0, i_c.input_w};
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_prefetch_wrap_base (
    .i_a(prefetch_wrap_i_a), .i_b(prefetch_wrap_i_b), .i_carry(1'b1),
    .o_sum(prefetch_wrap_base), .o_carry(unused_prefetch_x_carry[0])
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_prefetch_x (
    .i_a(32'(accepted_coordinate_q[0])), .i_b(pf_step_q), .i_carry(1'b0),
    .o_sum(prefetch_next_x), .o_carry(unused_prefetch_x_carry[1])
  );
  parallel_prefix_add #(.p_width(32), .p_group_width(8), .p_preserve_groups(1'b1)) u_prefetch_wrapped_x (
    .i_a(prefetch_wrap_base_q), .i_b(pf_step_q), .i_carry(1'b0),
    .o_sum(prefetch_wrapped_x), .o_carry(unused_prefetch_x_carry[2])
  );

  // 行宽为十六位，高半字的两种进位情况并行比较，低半字复用三进位关系。
  assign prefetch_range_a = {prefetch_wrap_base_q[15:0], accepted_coordinate_q[0][15:0], accepted_coordinate_q[0][15:0]};
  assign prefetch_range_b = {pf_step_q[15:0], pf_step_q[15:0], ~i_c.input_w};
  for (genvar range_index = 0; range_index < 3; range_index++) begin : g_prefetch_range_carry
    parallel_prefix_add #(.p_width(16), .p_group_width(4), .p_preserve_groups(1'b0)) u_carry (
      .i_a(prefetch_range_a[range_index]), .i_b(prefetch_range_b[range_index]),
      .i_carry(range_index == 0), .o_sum(unused_prefetch_range_sum[range_index]),
      .o_carry(prefetch_x_carry[range_index])
    );
  end
  for (genvar high_carry = 0; high_carry < 2; high_carry++) begin : g_prefetch_high_zero
    add_equal #(.p_width(16)) u_match (
      .i_a(accepted_coordinate_q[0][31:16]), .i_b(pf_step_q[31:16]),
      .i_target(high_carry == 0 ? 16'd0 : 16'hffff), .i_carry_in(1'b0),
      .o_equal(prefetch_high_zero[high_carry])
    );
  end
  assign prefetch_next_high_zero = prefetch_x_carry[1] ? prefetch_high_zero[1] : prefetch_high_zero[0];

  // 保存减法的无借位标志，并用两个候选坐标的进位确定模加法后的行边界。
  // 三个进位处于同一十六位范围，高半字与低半字共同形成完整边界条件。
`ifdef SYNTHESIS
  assign pf_crosses_row = !prefetch_next_high_zero |
          (prefetch_x_carry[1] ^ prefetch_base_no_borrow_q ^ prefetch_x_carry[2]);
`else
  always_comb begin
    case (^{accepted_coordinate_q[0][31:0], pf_step_q, i_c.input_w})
      1'b0, 1'b1: pf_crosses_row =
          !prefetch_next_high_zero |
          (prefetch_x_carry[1] ^ prefetch_base_no_borrow_q ^ prefetch_x_carry[2]);
      default: pf_crosses_row = prefetch_next_x >= 32'(i_c.input_w);
    endcase
  end
`endif

  // 核行片段和跨步窗口共用横坐标加法，模式选择在既有准备阶段完成。
  assign pf_window_ahead = !pf_stream_lookahead && i_c.windowed && tile_extent_q[0] == 32'd1 &&
      tile_extent_q[1] <= 32'(i_c.group_c) && (i_c.stride_h > 16'd1 || i_c.stride_w > 16'd1);
  // 窗口位移先保存，下一阶段计算低十六位进位，最终保留完整三十五位和值。
  always_comb begin
    if (i_c.output_w == 16'd1) pf_window_dx_next = 33'sd0;
    else if (pf_wrap_once) pf_window_dx_next = pf_ahead_two ? i_row_pair_dx : i_row_wrap_dx;
    else pf_window_dx_next = $signed(33'(i_c.stride_w) << pf_ahead_two);
  end
  parallel_prefix_add #(.p_width(16), .p_group_width(4), .p_preserve_groups(1'b0)) u_prefetch_horizontal_prepare (
    .i_a(accepted_coordinate_q[0][15:0]), .i_b(pf_horizontal_delta[15:0]), .i_carry(1'b0),
    .o_sum(unused_prefetch_horizontal_prepare_sum), .o_carry(prefetch_horizontal_low_carry)
  );

  assign pf_horizontal_delta = pf_window_ahead_q ?
      $signed(p_coord_w'(pf_window_dx_q)) : $signed(p_coord_w'(pf_fragment_dx_q));

  parallel_prefix_add #(.p_width(16), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_horizontal_low (
    .i_a(accepted_coordinate_q[0][15:0]), .i_b(pf_horizontal_delta[15:0]), .i_carry(1'b0),
    .o_sum(prefetch_horizontal_sum[15:0]), .o_carry(unused_prefetch_horizontal_low_carry)
  );
  parallel_prefix_add #(.p_width(p_coord_w-16), .p_group_width(4), .p_preserve_groups(1'b1)) u_prefetch_horizontal_high (
    .i_a(accepted_coordinate_q[0][p_coord_w-1:16]), .i_b(pf_horizontal_delta[p_coord_w-1:16]),
    .i_carry(prefetch_horizontal_low_carry_q),
    .o_sum(prefetch_horizontal_sum[p_coord_w-1:16]), .o_carry(unused_prefetch_horizontal_carry)
  );
`ifdef SYNTHESIS
  assign pf_horizontal_sum = $signed(prefetch_horizontal_sum);
`else
  always_comb begin
    case (^{accepted_coordinate_q[0], pf_horizontal_delta})
      1'b0, 1'b1: pf_horizontal_sum = $signed(prefetch_horizontal_sum);
      default: pf_horizontal_sum = accepted_coordinate_q[0] + pf_horizontal_delta;
    endcase
  end
`endif
  // 较大通道数按缓存行预测后续像素，提前保存新进入卷积窗口的输入行。
  assign pf_stream_lookahead = i_c.windowed && i_c.input_c >= 16'd16;
  always_comb begin
    pf_distance=pf_distance_q;
    pf_x=prefetch_next_x;pf_y=pf_y_base_q;
    if (pf_crosses_row) begin
      // 跨越输入行时保留横向余量，并预测下一输出行使用的同一核位置。
      pf_x=pf_stream_lookahead ? prefetch_wrapped_x : 32'd0;
      pf_y=pf_y_wrapped_q;
    end
    // 小通道片段按核行预测，换核行时保存相应的输入横坐标。
    pf_wrap_x=pf_horizontal_sum;
    if (!pf_stream_lookahead && i_c.windowed && tile_extent_q[0]==1 && tile_extent_q[1]<=32'(i_c.group_c) &&
        i_c.kernel_w>1 && i_c.kernel_h>1 && i_c.dilation_w==1 && i_c.dilation_h==1 &&
        pf_kernel_advance_q>=32'(i_c.kernel_w) &&
        pf_kernel_advance_q<2*32'(i_c.kernel_w)) begin
      pf_x=pf_wrap_x<0 ? 0 : 32'(pf_wrap_x);
      pf_y=32'(accepted_coordinate_q[1])+1;
    end
    // 小通道的跨步窗口预测后续两个输出位置，字偏移决定预测距离。

    pf_ahead_two=!pf_distance[0];
    pf_wrap_once=output_coordinate_q[0]==32'(i_last_output_col_q) ||
      (pf_ahead_two && output_coordinate_q[0]==32'(i_second_last_col_q));
    pf_wrap_twice=i_c.output_w==1 && pf_ahead_two;
    pf_window_x=pf_horizontal_sum;
    pf_window_y=accepted_coordinate_q[1]+$signed(p_coord_w'(pf_window_dy_q));
    if(pf_window_ahead_q) begin pf_x=32'(pf_window_x);pf_y=32'(pf_window_y);end
    pf_coordinate_valid=accepted_coordinate_q[0]>=0 && accepted_coordinate_q[1]>=0 && accepted_coordinate_q[0]<$signed(p_coord_w'(i_c.input_w)) &&
      accepted_coordinate_q[1]<$signed(p_coord_w'(i_c.input_h)) &&
      (!pf_window_ahead_q || (pf_window_row_valid_q && pf_window_x>=0 && pf_window_y>=0));
    pf_channel=i_epoch_o_sum[4];
    // 两路缓存分别保存当前和后续通道片段，引用标签采用实际物理地址。
    pf_next_fragment=i_fragment_image_fits && reference_q.index_valid && tile_extent_q[0]==1 &&
      tile_extent_q[1]==p_line_bytes && !i_c.input_s16 &&
      ((32'(i_c.group_offset)+pfa_origin_channel)&(p_line_bytes-1))==0 &&
      pfa_origin_channel+2*p_line_bytes<=32'(i_c.group_c) &&
      (!pf_window_ahead_q || pf_distance==p_line_bytes/4);
  end

  // 换核位移、预取距离和负一常量先压缩为两个操作数，完整结果在准备阶段保存。
  assign fragment_distance = 33'(pf_distance_q);
  assign fragment_xor = ~(i_tap_wrap_dx ^ fragment_distance);
  assign fragment_carry = i_tap_wrap_dx | fragment_distance;
  assign fragment_delta = fragment_xor + (fragment_carry << 1);

  // 预取状态和输出有效位复位，流水数据按状态选择在时钟边沿保存。
  always_ff @(posedge i_clk or negedge i_rst_n) begin
    if (!i_rst_n) begin
      o_prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else if (i_cfg_valid && i_cfg_ready) begin
      o_prefetch_phase <= '0;
      pf_offer_valid <= 1'b0;
    end else case (o_prefetch_phase)
      0: if (i_cache_port_valid && i_cache_port_ready && i_c.prefetch_enable) o_prefetch_phase <= 1;
      1: o_prefetch_phase <= 2;
      2: o_prefetch_phase <= 3;
      3: o_prefetch_phase <= 4;
      4: o_prefetch_phase <= 5;
      5: o_prefetch_phase <= 6;
      6: o_prefetch_phase <= 7;
      7: o_prefetch_phase <= 8;
      8: o_prefetch_phase <= 9;
      9: o_prefetch_phase <= 10;
      10: o_prefetch_phase <= 11;
      11: begin
        pf_offer_valid <= fragment_q || (coordinate_valid_q &&
            (o_pf_addr >> $clog2(p_line_bytes)) != (reference_q.address >> $clog2(p_line_bytes)));
        o_prefetch_phase <= 12;
      end
      default: o_prefetch_phase <= 0;
    endcase
  end
  always_ff @(posedge i_clk) begin
    if (!i_rst_n) begin
    end else if (i_cfg_valid && i_cfg_ready) begin
    end else begin
      case (o_prefetch_phase)
        0: if (i_cache_port_valid && i_cache_port_ready && i_c.prefetch_enable) begin
          // 预取上下文与实际接收地址同时保存，连续换行和换描述符时使用新坐标。
          accepted_coordinate_q[0] <= !p_register_cache_request && i_incoming_context ? i_incoming_ix :
              !p_register_cache_request && i_next_row_request ? i_next_row_ix : i_ix;
          accepted_coordinate_q[1] <= !p_register_cache_request ? i_request_y : i_iy;
          channel_q[0] <= !p_register_cache_request && i_incoming_context ? i_incoming_ch :
              !p_register_cache_request && i_next_row_request ? i_ch0 :
              !p_register_cache_request && i_stream_next_request ? i_stream_channel_full : i_ch;
          pfa_origin_channel <= !p_register_cache_request && i_incoming_context ? i_incoming_ch : i_ch0;
          output_coordinate_q[0] <= !p_register_cache_request && i_incoming_next_position_fast && i_incoming_context ?
              {16'd0, i_window_next_x} : !p_register_cache_request &&
              (i_next_row_request || (i_incoming_context && i_incoming_next_tile_fast)) ?
              (i_row_wrap ? 32'd0 : i_ox+32'd1) : i_ox;
          output_coordinate_q[1] <= !p_register_cache_request ? i_request_output_y : i_oy;
          pfa_kernel_x <= !p_register_cache_request && i_incoming_context ? i_incoming_kx :
              !p_register_cache_request && i_next_row_request ? i_kx0 : i_kx;
          pfa_kernel_y <= !p_register_cache_request && i_incoming_context ? 16'(i_incoming_ky) :
              !p_register_cache_request && i_next_row_request ? i_ky0_q : i_ky_q;
          tile_extent_q[0] <= !p_register_cache_request && i_incoming_context ? 32'(i_tile_rows) : 32'(i_rows_q);
          tile_extent_q[1] <= !p_register_cache_request && i_incoming_context ?
              (i_tile_cols=='0 ? 32'(p_size) : 32'(i_tile_cols)) : 32'(i_cols_q);
          reference_q.address <= p_register_cache_request ? i_request_addr_q : i_cache_req_addr;
          reference_q.index <= p_register_cache_request ? i_request_index_q : i_req_index;
          reference_q.epoch <= p_register_cache_request ? i_request_epoch_q : i_req_epoch;
          reference_q.index_valid <= p_register_cache_request ? i_request_index_valid_q : i_req_index_valid;
        end
        1: begin
          prefetch_wrap_base_q <= prefetch_wrap_base;
          prefetch_base_no_borrow_q <= prefetch_x_carry[0];
          pf_y_delta_q <= pf_y_delta;
          pf_y_wrap_delta_q <= pf_y_wrap_delta;
          pf_distance_q <= pf_stream_lookahead ? 32'd4 :
              (i_c.windowed ? 1+(((channel_q[0]-pfa_origin_channel)<<i_c.input_s16)>>2) : 32'd1);
        end
        2: begin
          // 窗口模式与位移在同一既有阶段保存，后级只选择稳定的运算输入。
          pf_window_ahead_q <= pf_window_ahead;
          pf_y_base_q <= pf_prepare_o_sum[0];
          pf_y_wrapped_q <= pf_prepare_o_sum[1];
          pf_kernel_advance_q <= pf_prepare_o_sum[2];
          // 固定提前四个缓存行的像素范围，最长限制为一行，便于逐行迭代。
          if (pf_stream_lookahead)
            pf_step_q <= (i_pf_step_base << 2) > {16'd0,i_c.input_w} ?
                {16'd0,i_c.input_w} : i_pf_step_base << 2;
          else
            pf_step_q <= i_pf_step_base * pf_distance_q;
          pf_fragment_dx_q <= fragment_delta;
          pf_window_dx_q <= pf_window_dx_next;
          pf_window_dy_q<=pf_wrap_twice ? (17'(i_c.stride_h)<<1) :
                            pf_wrap_once ? 17'(i_c.stride_h) : 17'd0;
          pf_window_row_valid_q<=pf_wrap_twice ?
              (i_c.output_h>1 && output_coordinate_q[1]<32'(i_second_last_row_q)) :
              (!pf_wrap_once || output_coordinate_q[1]<32'(i_retire_last_row_q));
        end
        3: begin
          prefetch_horizontal_low_carry_q <= prefetch_horizontal_low_carry;
        end
        4: begin
          projected_coordinate_q[0] <= pf_x;
          projected_coordinate_q[1] <= pf_y;
          channel_q[1] <= pf_channel;
          reference_retire_q <= i_retirement_result[1];
          fragment_q <= pf_next_fragment;
          coordinate_valid_q <= pf_coordinate_valid;
        end
        6: begin
          o_pf1_pixel <= i_prefetch_pixel_sum;
          o_pf1_retire <= i_retirement_result[1];
          coordinate_valid_q <= coordinate_valid_q &&
              projected_coordinate_q[0] < 32'(i_c.input_w) &&
              projected_coordinate_q[1] < 32'(i_c.input_h);
        end
        8: o_pf_address_term <= i_shared_channel_product[1][31:0];
        9: o_pf_address_term <= i_prefetch_byte_offset;
        10: o_pf_addr <= pf_address_calc;
        default: ;
      endcase
    end
  end

  always_comb begin
    pf_address_calc=i_prefetch_address_sum;
    o_pf_index_valid=reference_q.index_valid; o_pf_index=o_pf1_pixel; o_pf_epoch=reference_q.epoch;
    if (i_short_pixel_q)
      o_pf_index=o_pf1_pixel>>i_window_index_shift_q;
    if (!coordinate_valid_q && fragment_q) begin
      pf_address_calc=reference_q.address;o_pf_index=reference_q.index;o_pf_epoch=reference_q.epoch;
    end
    o_pf_valid=o_prefetch_phase==12 && pf_offer_valid;
  end

endmodule

`default_nettype wire
