// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在地址运算的输入和输出保存完整位宽，供寄存器路径测量使用。
module vector_read_address_measure (
  input wire logic clk,
  input wire logic [31:0] i_base,
  input wire logic [31:0] i_offset,
  input wire logic [15:0] i_channel,
  output logic [33:0] o_result
);
  logic [31:0] base_q, offset_q;
  logic [15:0] channel_q;
  logic [33:0] address;

  always_ff @(posedge clk) begin
    base_q <= i_base;
    offset_q <= i_offset;
    channel_q <= i_channel;
    o_result <= address;
  end
  vector_read_address_add u_address (
    .clk(clk), .i_base(base_q), .i_offset(offset_q), .i_channel(channel_q),
    .o_address(address[31:0]), .o_carry(address[33:32])
  );
endmodule

`default_nettype wire
