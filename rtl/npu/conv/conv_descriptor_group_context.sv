// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 起始通道和配置更新时保存高段范围，输入列数仅参与低段范围判断。
module conv_descriptor_group_context #(
  parameter int unsigned p_low_width = 5,
  parameter bit p_register_descriptor = 1'b1,
  localparam int p_high_width = 16 - p_low_width
) (
  input  wire logic clk,                      // 通道状态时钟
  input  wire logic rst_n,                    // 异步低有效复位
  input  wire logic i_configure,              // 当前周期接收新配置
  input wire logic [15:0] i_config_group,     // 新配置的组内通道数
  input wire logic [15:0] i_group,            // 当前配置的组内通道数
  input wire logic [15:0] i_channel,          // 当前描述符的起始通道
  input wire logic i_commit,                 // 当前周期提交描述符
  input wire logic i_invalid,                // 提交描述符未通过范围检查
  input wire logic i_fast,                   // 提交描述符复用已准备的通道位置
  input wire logic [15:0] i_commit_channel,   // 寄存描述符保存的起始通道
  input wire logic [15:0] i_window_channel,   // 已保存窗口的起始通道
  input wire logic i_commit_window,          // 直连描述符采用窗口起始通道
  input wire logic i_decode_write,           // 当前周期完成起始通道解码
  input wire logic [15:0] i_decode_channel,   // 解码完成的起始通道
  output logic o_high_before,            // 起始通道高段小于组宽高段
  output logic o_high_equal,             // 起始通道高段等于组宽高段
  output logic o_high_next_equal         // 起始通道高段加一后等于组宽高段
);

  //! 0. 辅助信号
  //! -------------

  logic [3:0][15:0] compare_channel;
  logic [3:0][15:0] compare_group;
  logic [3:0][2:0] compare_flags;
  logic [2:0] range_flags;
  logic [2:0] selected_flags;

  //! 1. 准备高段关系
  //! -----------------

  // 当前值、新配置、解码值和窗口值各自完成比较，写入事件只选择三位结果。
  assign compare_channel[0] = i_channel;
  assign compare_channel[1] = i_channel;
  assign compare_channel[2] = i_decode_channel;
  assign compare_channel[3] = p_register_descriptor ? i_commit_channel : i_window_channel;
  assign compare_group = {i_group, i_group, i_config_group, i_group};
  for (genvar source = 0; source < 4; source++) begin : g_candidate
    logic [p_high_width-1:0] high_i_a;
    logic [p_high_width-1:0] high_i_b;
    logic high_o_less;
    logic high_o_equal;
    logic high_next_o_equal;
    assign high_i_a = compare_channel[source][15:p_low_width];
    assign high_i_b = compare_group[source][15:p_low_width];
    parallel_unsigned_compare #(.p_width(p_high_width)) u_high (
      .i_a(high_i_a), .i_b(high_i_b),
      .o_less(high_o_less), .o_equal(high_o_equal)
    );
    increment_equal #(.p_width(p_high_width)) u_high_next (
      .i_a(high_i_a), .i_target(high_i_b), .o_equal(high_next_o_equal)
    );
    assign compare_flags[source] = {high_next_o_equal, high_o_equal, high_o_less};
  end

  //! 2. 保存高段关系
  //! -----------------

  // 配置、提交、解码依次处理；直连描述符沿用当前通道时保持原范围。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      range_flags <= 3'b010;
    end else if (i_configure) begin
      range_flags <= compare_flags[1];
    end else if (i_commit) begin
      if (i_invalid) begin
      end else if (i_fast) begin
        if (p_register_descriptor || i_commit_window) begin
          range_flags <= compare_flags[3];
        end
      end
    end else if (i_decode_write) begin
      range_flags <= compare_flags[2];
    end
  end

  //! 3. 输出高段关系
  //! -----------------

  // 已知状态读取保存结果；未知通道或组宽维持原分段比较的传播范围。
  always_comb begin
    selected_flags = compare_flags[0];
    case (^{i_channel, i_group})
      1'b0, 1'b1: selected_flags = range_flags;
      default: begin end
    endcase
  end
  assign {o_high_next_equal, o_high_equal, o_high_before} = selected_flags;

endmodule

`default_nettype wire
