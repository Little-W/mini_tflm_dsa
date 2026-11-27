// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 行请求寄存器的参考表达式，用于完整状态和四态传播比较。
module conv_im2col_row_request_reference #(
  parameter int p_coord_width = 35,
  parameter bit p_enabled = 1'b1
) (
  input wire logic i_clk, // 行请求寄存器时钟
  input wire logic i_rst_n, // 低有效异步复位
  input wire logic i_cfg_fire, // 当前周期接收新配置
  input wire logic i_error, // 当前任务发生错误
  input wire conv_im2col_pkg::conv_cfg_t i_configuration, // 当前卷积尺寸和空间步长
  input wire logic [1:0] i_step_phase, // 地址增量的配置准备阶段
  input wire logic i_base_valid, // 当前输出行起点地址有效
  input wire logic i_coordinate_valid, // 当前输入坐标与地址对应
  input wire logic i_geometry, // 当前描述符使用逐项几何计算
  input wire logic i_tile_commit, // 当前周期提交准备描述符
  input wire logic i_commit_next_row, // 提交项继承当前末行的下一空间位置
  input wire logic i_advance, // 当前输出被接收并推进至下一行
  input wire logic i_row_wrap, // 当前输出列推进时换行
  input wire logic [15:0] i_output_x, // 当前输出列坐标
  input wire logic [15:0] i_second_last_x, // 输出倒数第二列坐标
  input wire logic [31:0] i_base_address, // 当前输出行起点的字节地址
  input wire logic [31:0] i_base_pixel, // 当前输出行起点的线性像素索引
  input wire logic [1:0][p_coord_width-1:0] i_base_coordinate, // 当前输出行起点的输入列、行坐标
  input wire logic signed [32:0] i_wrap_dx, // 输出换行时的输入列位移
  input wire logic signed [32:0] i_pair_dx, // 两个输出位置内换行一次的输入列位移
  input wire logic signed [32:0] i_wrap_pixels, // 输出换行时的线性像素位移
  input wire logic [31:0] i_step_bytes, // 输出沿列推进的字节位移
  input wire logic [31:0] i_wrap_bytes, // 输出换行时的字节位移
  input wire logic [31:0] i_next_address, // 当前运行项计算出的下一行地址
  input wire logic [31:0] i_next_pixel, // 当前运行项计算出的下一行像素索引
  input wire logic [p_coord_width-1:0] i_next_y, // 当前运行项计算出的下一输入行坐标
  input wire logic i_next_padding, // 下一行起点需要填充
  output logic o_valid, // 下一行请求的寄存内容有效
  output logic [31:0] o_address, // 已准备的下一行字节地址
  output logic [31:0] o_pixel, // 已准备的下一行像素索引
  output logic [p_coord_width-1:0] o_y, // 已准备的下一输入行坐标
  output logic o_padding // 已准备的下一行填充标志
);
  if (p_enabled) begin : g_registered
    logic [31:0] pair_bytes_q, pair_pixels_q;
    logic [31:0] address_delta, pixel_delta, double_address, double_pixel;
    logic [1:0][p_coord_width-1:0] coordinate_delta, double_coordinate;
    logic [1:0] coordinate_valid;
    logic wraps_once, wraps_twice, context_valid, select_double;
    logic valid_q, padding_q;
    logic [31:0] address_q, pixel_q;
    logic [p_coord_width-1:0] y_q;

    // 配置乘积完成后保存两步位移，运行阶段只执行一次地址加法。
    always_ff @(posedge i_clk) begin
      if (i_step_phase == 2'd0) begin
        pair_bytes_q <= i_wrap_bytes + i_step_bytes;
        pair_pixels_q <= 32'(i_wrap_pixels) + 32'(i_configuration.stride_w);
      end
    end
    assign wraps_twice = i_configuration.output_w == 16'd1;
    assign wraps_once = i_row_wrap || i_output_x == i_second_last_x;
    assign address_delta = wraps_twice ? i_wrap_bytes << 1 :
        wraps_once ? pair_bytes_q : i_step_bytes << 1;
    assign pixel_delta = wraps_twice ? 32'(i_wrap_pixels) << 1 :
        wraps_once ? pair_pixels_q : 32'(i_configuration.stride_w) << 1;
    assign coordinate_delta[0] = wraps_twice ? p_coord_width'(i_wrap_dx) << 1 :
        wraps_once ? p_coord_width'(i_pair_dx) : p_coord_width'(i_configuration.stride_w) << 1;
    assign coordinate_delta[1] = wraps_twice ? p_coord_width'(i_configuration.stride_h) << 1 :
        wraps_once ? p_coord_width'(i_configuration.stride_h) : '0;
    conv_geometry_movement_add u_address (
      .i_base(i_base_address), .i_delta(address_delta), .o_sum(double_address)
    );
    conv_geometry_movement_add u_pixel (
      .i_base(i_base_pixel), .i_delta(pixel_delta), .o_sum(double_pixel)
    );
    for (genvar axis = 0; axis < 2; axis++) begin : g_coordinate
      conv_coordinate_step #(.p_width(p_coord_width)) u_step (
        .i_base(i_base_coordinate[axis]), .i_delta(coordinate_delta[axis]),
        .i_limit(axis == 0 ? i_configuration.input_w : i_configuration.input_h),
        .o_sum(double_coordinate[axis]), .o_valid(coordinate_valid[axis])
      );
    end

    assign context_valid = i_base_valid && i_coordinate_valid && !i_geometry;
    assign select_double = i_tile_commit ? i_commit_next_row : i_advance;
    always_ff @(posedge i_clk or negedge i_rst_n) begin
      if (!i_rst_n) valid_q <= 1'b0;
      else if (i_cfg_fire || i_error) valid_q <= 1'b0;
      else if (i_tile_commit) valid_q <= context_valid && i_commit_next_row;
      else valid_q <= context_valid;
    end
    // 数据与有效位采用同一推进条件，输出背压期间继续保存同一候选。
    always_ff @(posedge i_clk) begin
      if (select_double) begin
        address_q <= double_address;
        pixel_q <= double_pixel;
        y_q <= double_coordinate[1];
        padding_q <= !(&coordinate_valid);
      end else begin
        address_q <= i_next_address;
        pixel_q <= i_next_pixel;
        y_q <= i_next_y;
        padding_q <= i_next_padding;
      end
    end
    assign o_valid = valid_q;
    assign o_address = address_q;
    assign o_pixel = pixel_q;
    assign o_y = y_q;
    assign o_padding = padding_q;

`ifdef NPU_SIM_ASSERT
    // 独立运行地址用于核对提前保存项的代际和空间位置。
    always @(posedge i_clk) if (i_rst_n && valid_q && context_valid && !i_cfg_fire && !i_error) begin
      assert (address_q == i_next_address);
      assert (pixel_q == i_next_pixel);
      assert (y_q == i_next_y);
      assert (padding_q == i_next_padding);
    end
`endif
  end else begin : g_direct
    assign o_valid = 1'b1;
    assign o_address = i_next_address;
    assign o_pixel = i_next_pixel;
    assign o_y = i_next_y;
    assign o_padding = i_next_padding;
  end
endmodule
`default_nettype wire
