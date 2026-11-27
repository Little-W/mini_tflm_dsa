// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 选择普通读取、Softmax 查表和池化读取的完整地址分量。
// 候选分量并行准备，末级按查表、池化、普通读取的次序选择，保留四态 if 语义。
(* keep_hierarchy = "yes" *)
module vector_read_address_select (
  input wire logic i_lut_read, // 当前读取 Softmax 指数查找表
  input wire logic i_pool_read, // 当前读取池化输入数据
  input wire logic [31:0] i_load_base, // 普通读取的完整字节基址
  input wire logic [31:0] i_load_offset, // 普通读取相对基址的字节偏移
  input wire logic [31:0] i_lut_base, // Softmax 查找表的字节基址
  input wire logic [7:0] i_lut_index, // Softmax 查找表中四字节表项的索引
  input wire logic [31:0] i_pool_base, // 池化输入的完整字节基址
  input wire logic [31:0] i_pool_offset, // 池化输入相对基址的字节偏移
  input wire logic [15:0] i_pool_channel, // 池化输入当前通道的字节偏移
  output logic [31:0] o_base, // 本次读取选择的完整字节基址
  output logic [31:0] o_offset, // 本次读取选择的完整字节偏移
  output logic [15:0] o_channel // 本次读取选择的通道字节偏移
);
  //! 0. 末级读取来源选择
  //! --------------------

  always_comb begin
    o_base = i_load_base;
    o_offset = i_load_offset;
    o_channel = 16'd0;
    if (i_lut_read) begin
      o_base = i_lut_base;
      o_offset = {22'd0, i_lut_index, 2'b00};
    end else if (i_pool_read) begin
      o_base = i_pool_base;
      o_offset = i_pool_offset;
      o_channel = i_pool_channel;
    end
  end
endmodule

`default_nettype wire
