// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个无符号地址分量相加，完整保留三十四位结果。
(* keep_hierarchy = "yes" *)
module vector_read_address_add #(
  parameter bit p_preserve_groups = 1'b1
) (
  input wire logic clk,
  input wire logic [31:0] i_base,
  input wire logic [31:0] i_offset,
  input wire logic [15:0] i_channel,
  output logic [31:0] o_address,
  output logic [1:0] o_carry
);
  logic [33:0] base_extended, offset_extended, channel_extended;
  logic [33:0] address_sum, address_carry, address_fast, address_result;
  (* use_dsp = "simd" *) logic [18:0] partial_low;
  (* use_dsp = "simd" *) logic [16:0] partial_high;

  // 三项先压缩成两项，再独立计算十八位低段与十六位高段的和。
  assign base_extended = {2'b00, i_base};
  assign offset_extended = {2'b00, i_offset};
  assign channel_extended = {18'd0, i_channel};
  assign address_sum = base_extended ^ offset_extended ^ channel_extended;
  assign address_carry = ((base_extended & offset_extended) |
      (base_extended & channel_extended) | (offset_extended & channel_extended)) << 1;
  assign partial_low = {1'b0, address_sum[17:0]} + {1'b0, address_carry[17:0]};
  assign partial_high = {1'b0, address_sum[33:18]} + {1'b0, address_carry[33:18]};
  assign address_fast[17:0] = partial_low[17:0];
  // 低段进位与高段传播条件并行归并，各结果位分别完成修正。
  for (genvar bit_index = 0; bit_index < 16; bit_index++) begin : g_high
    if (bit_index == 0) begin : g_first
      assign address_fast[18+bit_index] = partial_high[bit_index] ^ partial_low[18];
    end else begin : g_later
      assign address_fast[18+bit_index] = partial_high[bit_index] ^
          (partial_low[18] & (&partial_high[bit_index-1:0]));
    end
  end

`ifndef SYNTHESIS
  logic [33:0] address_four_state;
  logic unused_address_carry;
  // 四态仿真保留三位分组加法的逐组未知值传播。
  parallel_prefix_add #(.p_width(34), .p_group_width(3), .p_preserve_groups(p_preserve_groups)) u_four_state (
      .i_a(address_sum), .i_b(address_carry), .i_carry(1'b0),
      .o_sum(address_four_state), .o_carry(unused_address_carry)
  );
`endif
  always_comb begin
    address_result = address_fast;
`ifndef SYNTHESIS
    case (^{i_base, i_offset, i_channel})
      1'b0, 1'b1: begin end
      default: address_result = address_four_state;
    endcase
`endif
  end
  assign {o_carry, o_address} = address_result;
endmodule

`default_nettype wire
