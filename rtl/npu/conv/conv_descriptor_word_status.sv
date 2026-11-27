// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在描述符提交边沿保存首个数据字的复用资格和填充状态。
// 当前响应先更新运行字的比较来源，检查周期直接使用已保存的一位结果。
module conv_descriptor_word_status #(
  parameter int p_tag_width = 29
) (
  input wire logic i_clk, // 描述符状态寄存器时钟
  input wire logic i_write, // 本周期提交有效的快速描述符
  input wire logic [p_tag_width-1:0] i_target_tag, // 准备项实际首地址的数据字标签
  input wire logic [p_tag_width-1:0] i_saved_tag, // 准备项随身保存的数据字标签
  input wire logic i_saved_valid, // 准备项保存的数据字有效
  input wire logic [p_tag_width-1:0] i_live_tag, // 当前运行数据字的标签
  input wire logic i_live_valid, // 当前运行数据字有效
  input wire logic [p_tag_width-1:0] i_response_tag, // 本周期接收响应对应的数据字标签
  input wire logic i_response_valid, // 本周期响应将写入运行数据字
  input wire logic i_padding, // 准备项首个输入位置需要填充
  output logic o_saved_hit, // 首地址命中随描述符保存的数据字
  output logic o_live_hit, // 首地址命中检查周期可见的运行数据字
  output logic o_padding // 检查周期的填充状态
);
  logic [p_tag_width-1:0] next_live_tag;
  logic next_live_valid;
  logic saved_equal, live_equal, saved_hit;

  // 提交与当前响应接收同周期时，下一周期的数据字来自本次响应。
  always_comb begin
    next_live_tag = i_live_tag;
    next_live_valid = i_live_valid;
    if (i_response_valid) begin
      next_live_tag = i_response_tag;
      next_live_valid = 1'b1;
    end
  end
  conv_descriptor_match #(.p_width(p_tag_width), .p_preserve_groups(1'b1)) u_saved_match (
    .i_a(i_target_tag), .i_b(i_saved_tag), .o_equal(saved_equal)
  );
  conv_descriptor_match #(.p_width(p_tag_width), .p_preserve_groups(1'b1)) u_live_match (
    .i_a(i_target_tag), .i_b(next_live_tag), .o_equal(live_equal)
  );
  assign saved_hit = i_saved_valid && saved_equal;
  always_ff @(posedge i_clk) begin
    if (i_write) begin
      o_saved_hit <= saved_hit;
      // 保存字在检查周期优先成为运行字，两项资格使用同一数据来源。
      o_live_hit <= saved_hit || (next_live_valid && live_equal);
      o_padding <= i_padding;
    end
  end
endmodule
`default_nettype wire
