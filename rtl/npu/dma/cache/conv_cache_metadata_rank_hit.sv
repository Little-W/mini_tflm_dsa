// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 更新模式提前提供，命中事件在末级同时控制顺序值和来源标记。
module conv_cache_metadata_rank_hit (
  input wire logic i_enable /* 允许当前更新 */, i_hit /* 当前请求命中 */, i_selected /* 当前缓存路已选中 */, i_windowed /* 采用窗口索引 */, i_hint_valid /* 下一次使用提示有效 */ , // 允许当前更新；当前请求命中；当前缓存路已选中；采用窗口索引；下一次使用提示有效
  output logic o_update // 本周期更新顺序元数据
);
  assign o_update = i_enable && i_hit && i_selected && (i_windowed || i_hint_valid);
endmodule

`default_nettype wire
