// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 固定缓存行跨度分别形成每个地址位的进位条件，低位字节偏移保持不变。
module conv_cache_next_line #(
  parameter int p_line_shift = 7
) (
  input wire logic [31:0] i_address, // 输入字节地址
  output logic [31:0] o_address, // 下一缓存行地址
  output logic o_carry // 地址递增的最高位进位
);
  logic [31:0] next_address;
  logic next_carry;
  if (p_line_shift > 0) begin : g_byte_offset
    assign next_address[p_line_shift-1:0] = i_address[p_line_shift-1:0];
  end
  assign next_address[p_line_shift] = ~i_address[p_line_shift];
  for (genvar address_bit = p_line_shift+1; address_bit < 32; address_bit++) begin : g_address_bit
    conv_cache_increment_bit #(.p_lower_width(address_bit-p_line_shift)) u_increment (
      .i_bit(i_address[address_bit]), .i_lower(i_address[p_line_shift+:address_bit-p_line_shift]),
      .o_bit(next_address[address_bit])
    );
  end
  assign next_carry = &i_address[31:p_line_shift];
`ifndef SYNTHESIS
  logic [31:0] four_state_address;
  logic four_state_carry;
  parallel_prefix_add #(.p_width(32), .p_group_width(4), .p_preserve_groups(1'b1)) u_four_state (
    .i_a(i_address), .i_b(32'(1) << p_line_shift), .i_carry(1'b0),
    .o_sum(four_state_address), .o_carry(four_state_carry)
  );
`endif
  always_comb begin
    {o_carry, o_address} = {next_carry, next_address};
`ifndef SYNTHESIS
    if ((^i_address) === 1'bx)
      {o_carry, o_address} = {four_state_carry, four_state_address};
`endif
  end
endmodule

`default_nettype wire
