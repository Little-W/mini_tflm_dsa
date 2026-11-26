// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按三位归并完整低位传播条件，独立计算通道索引高段加一或加二的各结果位。
(* keep_hierarchy = "yes" *)
module conv_stream_epoch_increment #(
  parameter int p_width = 14,
  parameter int p_increment = 1,
  localparam int p_first = p_increment == 2 ? 1 : 0,
  localparam int p_groups = (p_width-p_first+2)/3
) (
  input wire logic [p_width-1:0] i_value, // 尚未加入低段进位的高位通道索引
  output logic [p_width-1:0] o_value // 加入固定进位后的完整高段结果
);
  logic [p_groups-1:0] group_all;
  for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
    localparam int p_start = p_first+group_index*3;
    localparam int p_bits = p_width-p_start < 3 ? p_width-p_start : 3;
    (* keep = group_index < p_groups-1 *) logic local_all;
    assign local_all = &i_value[p_start+:p_bits];
    assign group_all[group_index] = local_all;
  end
  for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
    if (bit_index < p_first) begin : g_unmodified
      assign o_value[bit_index] = i_value[bit_index];
    end else if (bit_index == p_first) begin : g_first
      assign o_value[bit_index] = ~i_value[bit_index];
    end else begin : g_following
      localparam int p_full = (bit_index-p_first)/3;
      localparam int p_local = (bit_index-p_first)%3;
      logic carry;
      if (p_full == 0) begin : g_local_only
        assign carry = &i_value[p_first+:p_local];
      end else if (p_local == 0) begin : g_complete_groups
        assign carry = &group_all[p_full-1:0];
      end else begin : g_partial_group
        assign carry = (&group_all[p_full-1:0]) & (&i_value[p_first+p_full*3+:p_local]);
      end
      assign o_value[bit_index] = i_value[bit_index] ^ carry;
    end
  end
endmodule

`default_nettype wire
