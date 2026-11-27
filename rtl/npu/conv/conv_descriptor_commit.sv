// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 提交描述符的坐标、像素、核位置和地址算术，保持原有提交周期。
module conv_descriptor_commit #(
  parameter int p_size = 16,
  parameter int p_slot_w = 3,
  parameter int p_lanes = 2,
  parameter int p_line_bytes = 16,
  parameter bit p_register_descriptor = 1'b1,
  parameter int p_coord_w = 35,
  localparam int p_lane_bytes = p_lanes <= 4 ? 4 : (1 << $clog2(p_lanes)),
  localparam int p_cache_read_bytes = p_lane_bytes < p_line_bytes ? p_lane_bytes : p_line_bytes,
  localparam int p_word_shift = $clog2(p_cache_read_bytes),
  localparam int p_tile_count_w = $clog2(p_size+1),
  localparam int p_saved_group_lanes = p_lanes <= 16 ? p_lane_bytes : 4,
  localparam int p_prepared_tile_width = 458+2*p_coord_w+3*p_tile_count_w+p_slot_w+p_saved_group_lanes-p_word_shift
) (
  input wire logic [p_prepared_tile_width-1:0] i_prepared_tile_packed, // 已保存的待提交描述符
  input wire logic [p_prepared_tile_width-1:0] i_preparing_tile_packed, // 当前周期准备的描述符
  input wire conv_im2col_pkg::conv_cfg_t i_c, // 当前卷积配置
  input wire logic signed [32:0] i_row_wrap_dx, // 输出行回绕的水平坐标增量
  input wire logic signed [32:0] i_tap_wrap_dx, // 卷积核回绕的水平坐标增量
  input wire logic signed [32:0] i_tap_wrap_pixels, // 卷积核回绕的像素增量
  input wire logic signed [p_coord_w-1:0] i_tap_pair_dx, // 相邻核行之间的水平坐标增量
  input wire logic [31:0] i_tap_pair_pixels, // 相邻核行之间的像素增量
  input wire logic [31:0] i_tap_step_bytes, // 相邻核列的字节步长
  input wire logic [31:0] i_tap_wrap_bytes, // 核列回绕的字节步长
  input wire logic [31:0] i_tap_pair_bytes, // 相邻核行之间的字节步长
  input wire logic signed [p_coord_w-1:0] i_ix, // 当前提交位置的水平坐标
  input wire logic signed [p_coord_w-1:0] i_iy, // 当前提交位置的垂直坐标
  input wire logic [15:0] i_last_kernel_col_q, // 卷积核末列的保存值
  input wire logic [p_tile_count_w-1:0] i_active_columns, // 提交描述符的有效归约列数
  input wire logic [32:0] i_next_group, // 下一通道组的归约位置
  input wire logic [32:0] i_skip_group, // 跳过一个通道组的归约位置
  output logic [p_prepared_tile_width-1:0] o_committing_tile_packed, // 完成操作计算的提交描述符
  output logic [1:0] o_coordinate_valid // 当前提交坐标分别处于有效宽度和高度内
);

  //! 0. 辅助信号
  //! -------------

  localparam int p_prepared_count_w = p_tile_count_w;
  localparam int p_prepared_slot_w = p_slot_w;
  localparam int p_prepared_coord_w = p_coord_w;
  `include "conv_im2col_prepared_tile.svh"
  prepared_tile_t prepared_tile_q;
  prepared_tile_t preparing_tile;
  prepared_tile_t committing_tile;
  logic [1:0] committing_coordinate_valid;
  logic [31:0] committing_address_delta;
  logic committing_address_carry;
  logic [1:0][31:0] committing_address;
  logic signed [p_coord_w-1:0] committing_coordinate_dx;
  logic signed [p_coord_w-1:0] committing_coordinate_dy;
  logic [1:0] committing_coordinate_carry;
  logic [1:0][p_coord_w-1:0] committing_coordinate;
  logic signed [2:0] committing_tap_delta;
  logic signed [2:0] committing_kernel_x_delta;
  logic signed [2:0] committing_kernel_y_delta;
  logic [31:0] committing_pixel_delta;
  logic [15:0] committing_kernel_x_base;
  logic [9:0] committing_operation;
  logic committing_pixel_carry;
  logic [31:0] committing_tap;
  logic [15:0] committing_kernel_x;
  logic [15:0] committing_kernel_y;
  logic [31:0] committing_pixel;
  logic committing_kernel_last;

  //! 1. 计算提交字段
  //! -----------------

  assign prepared_tile_q = prepared_tile_t'(i_prepared_tile_packed);
  assign preparing_tile = prepared_tile_t'(i_preparing_tile_packed);
  if (p_register_descriptor) begin : g_commit_kernel_end
    // 末列关系直接比较模加等式，坐标保存与末列检查并行完成。
    conv_kernel_step_equal u_last (
      .i_base(committing_kernel_x_base), .i_step(committing_kernel_x_delta),
      .i_last(i_last_kernel_col_q), .o_equal(committing_kernel_last)
    );
  end else begin : g_direct_commit_kernel_end
    assign committing_kernel_last = 1'b0;
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
    logic [p_coord_w-1:0] parallel_sum;
    logic unused_sum_carry;
    parallel_prefix_add #(
      .p_width(p_coord_w), .p_group_width(4), .p_preserve_groups(1'b1),
      .p_dsp_split_width(16), .p_parallel_high_prefix(1'b1), .p_keep_carry(1'b0)
    ) u_coordinate_sum (
      .i_a(coordinate_i_a), .i_b(coordinate_i_b), .i_carry(coordinate_i_carry),
      .o_sum(parallel_sum), .o_carry(unused_sum_carry)
    );
    // 已知输入的低段进位直接参与各高段结果，未知输入保留定宽算术传播。
    always_comb begin
      coordinate_sum = coordinate_i_a + coordinate_i_b + p_coord_w'(coordinate_i_carry);
      case (^{coordinate_i_a, coordinate_i_b, coordinate_i_carry})
        1'b0, 1'b1: coordinate_sum = parallel_sum;
        default: ;
      endcase
    end
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
        committing_kernel_x_base = 16'd0;
        committing_kernel_y_delta = 3'sd1;
        committing_pixel_delta = 32'(i_tap_wrap_pixels);
      end
      committing_operation[3]: begin
        committing_tap_delta = 3'sd2;
        committing_kernel_x_base = 16'd0;
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
        committing_kernel_x_base = 16'd0;
        committing_kernel_x_delta = 3'sd1;
        committing_kernel_y_delta = -3'sd1;
        committing_pixel_delta = ~i_tap_pair_pixels;
        committing_pixel_carry = 1'b1;
      end
      default: ;
    endcase
  end
  conv_full_address_add u_tap_index (
    .i_a(prepared_tile_q.tap), .i_b(32'($signed(committing_tap_delta))), .o_sum(committing_tap)
  );
  assign committing_kernel_x = committing_kernel_x_base + 16'($signed(committing_kernel_x_delta));
  assign committing_kernel_y = prepared_tile_q.kernel_y + 16'($signed(committing_kernel_y_delta));
  conv_descriptor_add #(.p_width(32)) u_pixel_sum (
    .i_a(prepared_tile_q.pixel), .i_b(committing_pixel_delta),
    .i_carry(committing_pixel_carry), .o_sum(committing_pixel)
  );


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
    if (p_register_descriptor) begin : g_registered
      logic [31:0] address_i_a, address_i_b;
      logic address_i_carry;
      logic [31:0] address_sum;

      assign address_i_a = address_port == 0 ? prepared_tile_q.address : prepared_tile_q.group_address;
      assign address_i_b = committing_address_delta;
      assign address_i_carry = committing_address_carry;
      // 登记描述符在提交周期计算地址，与先前的数据字匹配独立执行。
      conv_descriptor_address_add #(.p_width(32)) u_address_sum (
        .i_a(address_i_a), .i_b(address_i_b), .i_carry(address_i_carry), .o_sum(address_sum)
      );
      assign committing_address[address_port] = address_sum;
    end else begin : g_direct
      assign committing_address[address_port] = '0;
    end
  end

  always_comb begin
    committing_tile = p_register_descriptor ? prepared_tile_q : preparing_tile;
    if (p_register_descriptor) begin
      committing_tile.active_columns = i_active_columns;
      committing_tile.next_group = i_next_group;
      committing_tile.skip_group = i_skip_group;
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

  //! 2. 输出提交结果
  //! -----------------

  assign o_committing_tile_packed = committing_tile;
  assign o_coordinate_valid = committing_coordinate_valid;

endmodule

`default_nettype wire
