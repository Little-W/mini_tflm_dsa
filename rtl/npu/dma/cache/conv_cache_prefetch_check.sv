// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 预取查询的有效条件提前归并，替换发送只在末级使当前查询失效。
(* keep_hierarchy = "yes" *)
module conv_cache_prefetch_check (
  input wire logic i_configure, // 当前周期接收缓存配置
  input wire logic i_pending, // 已保存有效的活动预取项
  input wire logic i_lookup_ready, // 预取标签与组号快照就绪
  input wire logic i_fill_busy, // 本周期更新填充元数据
  input wire logic i_fill_set_match, // 填充元数据与预取查询使用同一组
  input wire logic i_launch, // 本周期开始替换填充
  input wire logic i_launch_set_match, // 替换填充与预取查询使用同一组
  output logic o_next_checked // 下一周期可以使用保存的预取命中结果
);
  logic lookup_eligible;
  conv_cache_prefetch_check_ready u_ready (
    .i_pending(i_pending), .i_lookup_ready(i_lookup_ready),
    .i_fill_busy(i_fill_busy), .i_fill_set_match(i_fill_set_match),
    .o_eligible(lookup_eligible)
  );
  always_comb begin
    o_next_checked = lookup_eligible && !(i_launch && i_launch_set_match);
    if (i_configure) o_next_checked = 1'b0;
  end
endmodule

`default_nettype wire
