// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 对释放行号完成四种固定位移之一的选择，两个实例分别处理低位和高位移位量。
// 每个输出位仅使用四个数据候选和两个选择位，模块边界保持单级选择结构。
(* keep_hierarchy = "yes" *)
module conv_cache_retire_shift #(
  parameter int unsigned p_step = 1 // 相邻候选之间的右移位数
) (
  input wire logic [17:0] i_row, // 当前级待移位的行号
  input wire logic [1:0] i_shift, // 当前级选择的移位候选编号
  output logic [17:0] o_row // 完成本级右移后的行号
);
  always_comb begin
    case (i_shift)
      2'd0: o_row = i_row;
      2'd1: o_row = i_row >> p_step;
      2'd2: o_row = i_row >> (2*p_step);
      2'd3: o_row = i_row >> (3*p_step);
      default: o_row = 'x;
    endcase
  end
endmodule

`default_nettype wire
