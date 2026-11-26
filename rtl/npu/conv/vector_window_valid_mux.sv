// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 从窗口返回数据的半组中选择一个通道有效位，保存独立的四路选择层次。
(* keep_hierarchy = "yes" *)
module vector_window_valid_mux (
    input wire logic [3:0] i_values, // 当前半组的四个通道有效位
    input wire logic [1:0] i_index, // 当前半组内的通道编号
    output logic o_value // 所选通道的有效位
);
    assign o_value = i_values[i_index];
endmodule

`default_nettype wire
