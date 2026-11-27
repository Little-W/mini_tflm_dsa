// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 将输入基址、像素通道乘积和组内偏移压缩为两个加数，计算完整三十二位组基址。
module conv_group_base_address (
  input wire logic [31:0] i_input_base, // 输入张量的字节基址
  input wire logic [31:0] i_channel_product, // 当前像素与通道数量的模乘积
  input wire logic [15:0] i_group_offset, // 当前通道组的元素偏移
  input wire logic i_input_s16, // 每个输入元素占用两个字节
  output logic [31:0] o_address // 按三十二位地址范围回绕的组基址
);
  logic [31:0] product_bytes, group_bytes;
  logic [31:0] sum_bits, carry_bits, prepared_address;

  // 元素大小分别作用于两个偏移，逐位压缩不依赖低位进位传播。
  assign product_bytes = i_channel_product << i_input_s16;
  assign group_bytes = {16'd0, i_group_offset} << i_input_s16;
  assign sum_bits = i_input_base ^ product_bytes ^ group_bytes;
  assign carry_bits = ((i_input_base & product_bytes) |
      (i_input_base & group_bytes) | (product_bytes & group_bytes)) << 1;
  conv_full_address_add u_sum (
    .i_a(sum_bits), .i_b(carry_bits), .o_sum(prepared_address)
  );

  // 未知输入保留完整定宽算术的传播，确定输入只经过一次完整进位计算。
  always_comb begin
    o_address = i_input_base + ((i_channel_product + 32'(i_group_offset)) << i_input_s16);
    case (^{i_input_base, i_channel_product, i_group_offset, i_input_s16})
      1'b0, 1'b1: o_address = prepared_address;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
