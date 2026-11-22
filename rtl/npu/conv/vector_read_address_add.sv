// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个无符号地址分量进行完整宽度组合加法。
module vector_read_address_add #(
  parameter bit p_preserve_groups = 1'b1
) (
  input logic clk,
  input logic [31:0] i_base,
  input logic [31:0] i_offset,
  input logic [15:0] i_channel,
  output logic [31:0] o_address,
  output logic [1:0] o_carry
);
  logic [33:0] base_extended, offset_extended, channel_extended;
  logic [33:0] address_sum, address_carry, address_result;
  logic unused_address_carry;

  // 三项先压缩成两项，再以三位分组求和，保留两个地址进位位。
  assign base_extended = {2'b00, i_base};
  assign offset_extended = {2'b00, i_offset};
  assign channel_extended = {18'd0, i_channel};
  assign address_sum = base_extended ^ offset_extended ^ channel_extended;
  assign address_carry = ((base_extended & offset_extended) |
      (base_extended & channel_extended) | (offset_extended & channel_extended)) << 1;
  parallel_prefix_add #(.p_width(34), .p_group_width(3), .p_preserve_groups(p_preserve_groups)) u_address_sum (
      .i_a(address_sum), .i_b(address_carry), .i_carry(1'b0),
      .o_sum(address_result), .o_carry(unused_address_carry)
  );
  assign {o_carry, o_address} = address_result;
endmodule

`default_nettype wire
