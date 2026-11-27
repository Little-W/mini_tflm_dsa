// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在请求保存边沿同时寄存像素位置和窗口缩放格式，随后组合生成完整索引。
// 像素来源选择与动态移位分居寄存器两侧，保持同周期请求元数据和四态传播。
module conv_request_index_register (
  input wire logic i_clk, // 请求元数据寄存器时钟
  input wire logic i_write, // 当前边沿允许替换请求元数据
  input wire logic [31:0] i_pixel, // 当前请求在窗口缩放之前的完整像素位置
  input wire logic i_short_pixel, // 当前请求需要按窗口粒度缩放像素位置
  input wire logic [4:0] i_shift, // 与当前像素对应的窗口右移位数
  input wire logic [31:0] i_reference, // 与像素和格式对应的完整索引，保留未知输入传播
  output logic [31:0] o_index, // 当前保存请求的完整窗口索引
  output wire logic [31:0] o_pixel // 当前保存请求在窗口缩放之前的完整像素位置
);
  logic [31:0] pixel_q, reference_q;
  logic known_q;
  logic [4:0] shift_q;
  assign o_pixel = pixel_q;

  always_ff @(posedge i_clk) begin
    if (i_write) begin
      pixel_q <= i_pixel;
      shift_q <= i_shift & {5{i_short_pixel}};
      case (^{i_pixel, i_short_pixel, i_shift, i_reference})
        1'b0, 1'b1: known_q <= 1'b1;
        default: known_q <= 1'b0;
      endcase
      reference_q <= i_reference;
    end
  end

  always_comb begin
    o_index = reference_q;
    case (known_q)
      1'b1: o_index = pixel_q >> shift_q;
      default: begin end
    endcase
  end
endmodule
`default_nettype wire
