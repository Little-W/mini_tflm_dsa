// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行计算三十二位完整地址和值，含未知输入时保持普通加法的逐位传播。
module conv_full_address_add (
  input wire logic [31:0] i_a, // 起始地址或完整索引
  input wire logic [31:0] i_b, // 本次增加的定宽偏移
  output logic [31:0] o_sum // 三十二位模加法结果
);
  logic [31:0] prepared_sum;
  conv_geometry_movement_add u_sum (
    .i_base(i_a), .i_delta(i_b), .o_sum(prepared_sum)
  );
  always_comb begin
    o_sum = i_a + i_b;
    case (^{i_a, i_b})
      1'b0, 1'b1: o_sum = prepared_sum;
      default: ;
    endcase
  end
endmodule

`default_nettype wire
