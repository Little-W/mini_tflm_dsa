// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 需求和预取分别准备填充资格，当前请求的占用条件只参与最后一级发送选择。
// 预取发送结果独立输出，预取队列的退休控制直接使用对应分支。
(* keep_hierarchy = "yes" *)
module conv_cache_select_launch (
  input wire logic i_capacity_ready, // 填充容量与已保存替换快照均已就绪
  input wire logic i_victim_conflict, // 当前需求占用待替换的缓存路
  input wire logic i_prefetch, // 当前替换快照属于预取请求
  input wire logic i_prefetch_ready, // 预取地址及查询状态满足发送条件
  input wire logic i_demand_ready, // 需求地址及查询状态满足发送条件
  input wire logic i_hint_busy, // 提示查询占用当前替换组的元数据
  input wire logic i_fire, // 本周期消费工作请求
  input wire logic i_set_match, // 工作请求与替换快照使用同一组
  input wire logic i_hit, // 工作请求命中缓存
  output logic o_launch, // 当前替换请求可以开始填充
  output logic o_prefetch_launch // 当前预取请求可以开始填充
);
  logic prefetch_ready, demand_ready;
  conv_cache_select_launch_ready u_ready (
    .i_capacity_ready(i_capacity_ready), .i_victim_conflict(i_victim_conflict),
    .i_prefetch(i_prefetch), .i_prefetch_ready(i_prefetch_ready),
    .i_demand_ready(i_demand_ready), .i_hint_busy(i_hint_busy), .i_hit(i_hit),
    .o_prefetch_ready(prefetch_ready), .o_demand_ready(demand_ready)
  );

  logic launch_parallel;
  conv_cache_select_launch_merge u_merge (
    .i_prefetch_ready(prefetch_ready), .i_demand_ready(demand_ready),
    .i_fire(i_fire), .i_set_match(i_set_match), .i_hit(i_hit), .o_launch(launch_parallel)
  );
  always_comb begin
    o_prefetch_launch = prefetch_ready && !(i_fire && (i_set_match || !i_hit));
    o_launch = launch_parallel;
    case (^{i_capacity_ready, i_victim_conflict, i_prefetch, i_prefetch_ready,
             i_demand_ready, i_hint_busy, i_fire, i_set_match, i_hit})
      1'b0, 1'b1: begin end
      default: begin
        // 未知控制保留条件选择的逐位合并及过程条件赋值语义。
        o_launch = i_capacity_ready &&
            (i_prefetch ?
                (i_prefetch_ready && !(i_hint_busy || (i_fire && (i_set_match || !i_hit)))) :
                (i_demand_ready && !i_hit && !(i_hint_busy || (i_fire && i_set_match))));
        if (o_launch && i_victim_conflict) o_launch = 1'b0;
        o_prefetch_launch = o_launch && i_prefetch;
      end
    endcase
  end
endmodule

`default_nettype wire
