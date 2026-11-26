// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 同周期请求参与空闲判断，开始事件和后台空闲条件并行计算。
module kernel_request_idle (
    input  wire logic i_request /* 当前客户端请求一次装载 */,
    input  wire logic i_granted /* 共享 DMA 已授予当前请求 */,
    input  wire logic i_quiescent /* 此前没有活动装载事务 */,
    output logic o_start /* 请求与授予同时成立的启动事件 */,
    output logic o_idle /* 当前没有活动事务且未接收新请求 */
);
    assign o_start = i_request && i_granted;
    assign o_idle = i_quiescent && !(i_request && i_granted);
endmodule

`default_nettype wire
