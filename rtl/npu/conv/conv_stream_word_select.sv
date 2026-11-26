// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 选择行切换、卷积核切换或连续地址对应的字内有效范围。
// 保留行末优先级和条件未知时逐位合并的四态语义。
(* keep_hierarchy = "yes" *)
module conv_stream_word_select #(
    parameter int unsigned p_bytes = 8
) (
    input  wire logic i_chunk_end, // 当前输出分块到达行末。
    input  wire logic i_group_end, // 当前传输到达通道组末尾。
    input  wire logic i_coordinate_valid, // 下一卷积核坐标有效。
    input  wire logic [p_bytes-1:0] i_row, // 下一输出行地址的字内范围。
    input  wire logic [p_bytes-1:0] i_tap, // 下一卷积核地址的字内范围。
    input  wire logic [p_bytes-1:0] i_step, // 连续地址的字内范围。
    output logic [p_bytes-1:0] o_available // 按当前运行事件选择的字内范围。
);
    assign o_available = i_chunk_end ? i_row :
        (i_group_end && i_coordinate_valid) ? i_tap : i_step;
endmodule

`default_nettype wire
