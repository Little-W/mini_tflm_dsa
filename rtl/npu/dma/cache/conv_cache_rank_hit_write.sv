// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 运行资格与命中事件独立计算，清除保持所有来源的最高写入优先级。
(* keep_hierarchy = "yes" *)
module conv_cache_rank_hit_write (
  input wire logic i_clear /* 清除全部来源 */, i_eligible /* 命中写入具备资格 */, i_hit /* 当前发生命中 */ , // 清除全部来源；命中写入具备资格；当前发生命中
  output logic o_write // 命中来源存储写使能
);
  assign o_write = i_clear || (i_eligible && i_hit);
endmodule

`default_nettype wire
