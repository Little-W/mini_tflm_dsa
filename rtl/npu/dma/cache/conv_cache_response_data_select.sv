// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 每路完整响应已经准备，较高编号的命中路在末级保持选择优先级。
module conv_cache_response_data_select #(
  parameter int p_ways = 2,
  parameter int p_width = 128
) (
  input wire logic [p_ways-1:0] i_hits, // 各缓存路命中结果
  input wire logic [p_ways-1:0][p_width-1:0] i_data, // 各缓存路响应数据
  output logic [p_width-1:0] o_data // 按命中优先级选择的响应数据
);
  always_comb begin
    o_data = i_data[0];
    for (int way = 1; way < p_ways; way++) begin
      if (i_hits[way]) o_data = i_data[way];
    end
  end
endmodule

`default_nettype wire
