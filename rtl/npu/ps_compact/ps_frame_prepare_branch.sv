// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 以保存的请求资格和帧关系选择空闲接收或完成交接的部分和帧分支。
// 同址单行提交仍优先于新帧读取，分支条件在最终组合层统一合并。
(* keep_hierarchy = "yes" *)
module ps_frame_prepare_branch (
    input wire logic i_request_qualified, // 已保存的合法且容量足够的待处理请求
    input wire logic i_initial_or_other, // 新请求初始化数据或访问不同的帧编号
    input wire logic i_encoder_done, // 编码器在本周期完成一行提交
    input wire logic i_commit_next_complete, // 当前提交后本帧的全部行已完成
    input wire logic i_single_row, // 当前帧只包含一行数据
    input wire logic i_branch_enable, // 当前命令状态允许选择此接收分支
    output logic o_ready // 当前请求可由所选分支接收
);
    assign o_ready = i_request_qualified && i_branch_enable &&
        (i_initial_or_other || !i_encoder_done || !i_commit_next_complete || !i_single_row);
endmodule

`default_nettype wire
