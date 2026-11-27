// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较正式请求与同步读取的预读内容，形成多项队列的地址匹配资格。
// 地址比较和控制条件并行归并，组号匹配只参与末级资格，接收及容量由请求通路处理。
(* keep_hierarchy = "yes" *)
module conv_cache_queued_preview (
  input wire logic i_preview_selected, // 前一拍同步读取了有效预读地址
  input wire logic i_queue_empty, // 正式请求队列当前为空
  input wire logic i_foreground_idle, // 前台读取状态当前空闲
  input wire logic [31:0] i_request_address, // 正式请求的完整字节地址
  input wire logic [31:0] i_saved_address, // 预读保存的完整字节地址
  input wire logic i_set_match, // 正式请求与预读快照的缓存组号相同
  input wire logic i_saved_range, // 预读时保存的范围检查结果
  output logic o_match // 地址和状态允许使用已经同步读取的内容
);
  localparam int unsigned p_address_groups = 11;
  localparam int unsigned p_conditions = p_address_groups+3;
  localparam int unsigned p_partitions = (p_conditions+5)/6;
  (* keep = 1 *) logic [p_address_groups-1:0] group_equal;
  logic [p_conditions-1:0] conditions;
  (* keep = 1 *) logic [p_partitions-1:0] partition_match;
  logic combined_match;

  for (genvar group_index = 0; group_index < p_address_groups; group_index++) begin : g_address
    localparam int unsigned p_first = 3*group_index;
    localparam int unsigned p_bits = 32-p_first < 3 ? 32-p_first : 3;
    assign group_equal[group_index] =
        i_request_address[p_first+:p_bits] == i_saved_address[p_first+:p_bits];
  end
  assign conditions = {i_preview_selected, i_queue_empty, i_foreground_idle, group_equal};
  for (genvar partition_index = 0; partition_index < p_partitions; partition_index++) begin : g_partition
    localparam int unsigned p_first = 6*partition_index;
    localparam int unsigned p_bits = p_conditions-p_first < 6 ? p_conditions-p_first : 6;
    assign partition_match[partition_index] = &conditions[p_first+:p_bits];
  end
  assign combined_match = (&partition_match) && i_set_match;
  always_comb begin
    o_match = 1'b0;
    case (combined_match)
      1'b1: o_match = 1'b1;
      default: begin end
    endcase
    case (i_saved_range)
      1'b0, 1'b1: begin end
      default: o_match = 1'b0;
    endcase
  end
endmodule

`default_nettype wire
