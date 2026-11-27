// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 计算替换快照的下一周期有效位，分别准备命中与替换冲突的四种候选结果。
// 两个查询结果共同参与末级选择，配置清除和快照更新保持原有时钟周期。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_hold (
    input wire logic i_configure, // 当前周期接收缓存配置
    input wire logic i_valid, // 当前替换快照有效
    input wire logic i_metadata_busy, // 快照对应的元数据正在更新
    input wire logic i_prefetch, // 当前快照属于预取请求
    input wire logic i_prefetch_snapshot, // 预取地址与状态允许保留快照
    input wire logic i_demand_snapshot, // 普通请求地址与状态允许保留快照
    input wire logic i_retire_eligible, // 替换决策和填充资源允许结束快照
    input wire logic i_prefetch_ready, // 预取查询已经就绪
    input wire logic i_demand_retire, // 普通请求查询就绪且没有并发完成
    input wire logic i_fire, // 本周期接收工作请求
    input wire logic i_hit, // 当前查询命中缓存
    input wire logic i_victim_conflict, // 当前读取命中待替换的缓存路
    input wire logic i_launch, // 本周期产生新的替换候选
    input wire logic i_candidate_busy, // 新候选的元数据正在更新
    output logic o_next_valid // 下一周期替换快照有效
);
    (* keep = 1 *) logic [3:0] hold_outcome;
    logic selected_hold;

    // 保持和结束条件先按四种固定查询结果计算，共用原有请求资格。
    for (genvar outcome = 0; outcome < 4; outcome++) begin : g_outcome
        localparam bit p_hit = (outcome & 1) != 0;
        localparam bit p_conflict = (outcome & 2) != 0;
        assign hold_outcome[outcome] =
            (i_prefetch ? i_prefetch_snapshot : (i_demand_snapshot && !p_hit)) &&
            !(i_retire_eligible &&
              (i_prefetch ? (i_prefetch_ready && !(i_fire && !p_hit) && !p_conflict) :
                            i_demand_retire));
    end

    // 未知查询结果按完整逻辑关系传播，保留仿真中的四态控制行为。
    always_comb begin
        selected_hold = hold_outcome[{i_victim_conflict, i_hit}];
        case (^{i_victim_conflict, i_hit})
            1'b0, 1'b1: begin end
            default: begin
                selected_hold =
                        (i_prefetch ? i_prefetch_snapshot : (i_demand_snapshot && !i_hit)) &&
                        !(i_retire_eligible &&
                          (i_prefetch ? (i_prefetch_ready && !(i_fire && !i_hit) && !i_victim_conflict) :
                                        i_demand_retire));
            end
        endcase
    end
    conv_cache_snapshot_valid u_next_valid (
        .i_configure(i_configure), .i_valid(i_valid), .i_metadata_busy(i_metadata_busy),
        .i_hold(selected_hold), .i_launch(i_launch), .i_candidate_busy(i_candidate_busy),
        .o_next_valid(o_next_valid)
    );
endmodule

`default_nettype wire
