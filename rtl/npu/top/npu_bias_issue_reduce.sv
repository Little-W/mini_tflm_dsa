// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 在比较分组的末级同时合并输入发送和数据流资格，保持各条件的并行路径。
(* keep_hierarchy = "yes" *)
module npu_bias_issue_reduce #(
    parameter int unsigned p_groups = 3
) (
    input wire logic [p_groups-1:0] i_group_equal, // 各相邻位比较分组均满足定宽加一关系
    input wire logic i_eligible, // 输入数据和计算控制已经允许发送
    input wire logic i_mode_eligible, // 本数据流与地址低位检查通过
    output logic o_qualified // 本通道地址为零且全部发送资格有效
);
    assign o_qualified = (&i_group_equal) && i_eligible && i_mode_eligible;
endmodule

`default_nettype wire
