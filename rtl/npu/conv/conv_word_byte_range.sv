// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 独立检查固定字节编号是否落在当前字内剩余范围中。
(* keep_hierarchy = "yes" *)
module conv_word_byte_range #(
  parameter int p_offset_width = 3,
  parameter int p_word_bytes = 8,
  parameter int p_byte_index = 0
) (
  input wire logic [p_offset_width-1:0] i_offset, // 当前地址在完整读取字内的字节偏移
  output logic o_available // 固定字节编号仍处于当前读取字的覆盖范围
);
  assign o_available = {1'b0, i_offset} < (p_offset_width+1)'(p_word_bytes-p_byte_index);
endmodule

`default_nettype wire
