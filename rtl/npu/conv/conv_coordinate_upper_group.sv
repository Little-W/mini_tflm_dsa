// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 检查连续高位的零值进位关系，两位结果只需要六个输入信号。
(* keep_hierarchy = "yes" *)
module conv_coordinate_upper_group #(
  parameter int p_bits = 2
) (
  input wire logic [p_bits:0] i_a, // 本组坐标基值，最低位提供相邻进位条件。
  input wire logic [p_bits:0] i_b, // 本组步进量，最低位提供相邻进位条件。
  output logic o_valid // 本组各位均满足和值为零的条件。
);
  logic [p_bits-1:0] bit_valid;
  for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
    assign bit_valid[bit_index] = ~(i_a[bit_index+1] ^ i_b[bit_index+1] ^
        (i_a[bit_index] | i_b[bit_index]));
  end
  assign o_valid = &bit_valid;
endmodule

`default_nettype wire
