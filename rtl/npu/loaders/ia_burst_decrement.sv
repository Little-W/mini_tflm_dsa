// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 将矩阵块每行拍数转换为八位突发长度减一字段，保持完整输入的四态传播。
(* keep_hierarchy = "yes" *)
module ia_burst_decrement #(
    parameter int unsigned p_width = 32
) (
    input wire logic [p_width-1:0] i_beats, // 当前行需要传输的数据拍数。
    output logic [7:0] o_length // 八位突发拍数减一字段。
);
    assign o_length = 8'(i_beats - p_width'(1));
endmodule
`default_nettype wire
