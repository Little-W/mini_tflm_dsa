// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据当周期装载完成和分组退休事件选择已并行计算的发送资格。
(* keep_hierarchy = "yes" *)
module ia_completion_select (
    input wire logic [1:0] i_events, // 高位为当前分组退休事件，低位为矩阵块装载完成事件
    input wire logic [3:0][1:0] i_ready, // 四种事件组合下的数据有效和分组发送就绪条件
    output logic [1:0] o_ready // 选定的数据有效标志和分组发送就绪标志
);
    assign o_ready = i_ready[i_events];
endmodule

`default_nettype wire
