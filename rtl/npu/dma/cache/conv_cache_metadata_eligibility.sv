// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 请求、范围、运行模式和快照就绪条件分别形成后一次归并。
module conv_cache_metadata_eligibility #(
  parameter int p_conditions = 5
) (
  input wire logic [p_conditions-1:0] i_conditions, // 并行形成的资格条件
  output logic o_eligible // 全部资格条件成立
);
  assign o_eligible = &i_conditions;
endmodule

`default_nettype wire
