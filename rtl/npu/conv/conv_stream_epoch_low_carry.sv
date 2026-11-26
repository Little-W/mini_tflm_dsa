// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 对短通道低段独立计算最高进位，分组产生条件与低段和值并行形成。
(* keep_hierarchy = "yes" *)
module conv_stream_epoch_low_carry #(
  parameter int p_width = 4
) (
  input wire logic [p_width-1:0] i_a, // 组偏移的低位部分
  input wire logic [p_width-1:0] i_b, // 通道坐标的低位部分
  output logic o_carry // 两个低位部分相加的最高进位
);
  localparam int p_low_groups = (p_width+1)/2;
  logic [p_low_groups-1:0] low_generate, low_propagate, low_carry_terms;
  // 低段按两位独立形成产生条件，全部组同时参与最高进位的归并。
  for (genvar group_index = 0; group_index < p_low_groups; group_index++) begin : g_low
    localparam int p_start = group_index*2;
    localparam int p_bits = p_width-p_start < 2 ? 1 : 2;
    (* keep = "true" *) logic group_generate;
    (* keep = group_index > 0 *) logic group_propagate;
    if (p_bits == 1) begin : g_single
      assign group_generate = i_a[p_start] && i_b[p_start];
      assign group_propagate = i_a[p_start] || i_b[p_start];
    end else begin : g_pair
      assign group_generate = (i_a[p_start+1] && i_b[p_start+1]) ||
          ((i_a[p_start+1] || i_b[p_start+1]) && i_a[p_start] && i_b[p_start]);
      assign group_propagate = (i_a[p_start+1] || i_b[p_start+1]) &&
          (i_a[p_start] || i_b[p_start]);
    end
    assign low_generate[group_index] = group_generate;
    assign low_propagate[group_index] = group_propagate;
    if (group_index == p_low_groups-1) begin : g_last
      assign low_carry_terms[group_index] = group_generate;
    end else begin : g_lower
      assign low_carry_terms[group_index] = group_generate &&
          (&low_propagate[p_low_groups-1:group_index+1]);
    end
  end
  assign o_carry = |low_carry_terms;
endmodule

`default_nettype wire
