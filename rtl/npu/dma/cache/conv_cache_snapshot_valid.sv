// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 合并替换快照的保持、启动和配置清除条件，形成单比特寄存器输入。
(* keep_hierarchy = "yes" *)
module conv_cache_snapshot_valid (
    input wire logic i_configure, // 当前周期接收缓存配置
    input wire logic i_valid, // 当前快照有效
    input wire logic i_metadata_busy, // 当前快照元数据正在更新
    input wire logic i_hold, // 查询结果允许保持当前快照
    input wire logic i_launch, // 本周期产生新的替换候选
    input wire logic i_candidate_busy, // 新候选的元数据正在更新
    output logic o_next_valid // 下一周期的快照有效位
);
    always_comb begin
        o_next_valid = i_launch && !i_candidate_busy;
        if (i_valid) o_next_valid = !i_metadata_busy && i_hold;
        if (i_configure) o_next_valid = 1'b0;
    end
endmodule

`default_nettype wire
