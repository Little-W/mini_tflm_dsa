// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 根据二位索引选择四组权重列数据中的一组。
(* keep_hierarchy = "yes" *)
module kernel_column_select4 #(
    parameter int unsigned p_width = 16
) (
    input wire logic [1:0] i_select, // 候选数据选择条件
    input wire logic [p_width-1:0] i_data0, // 索引为零的权重列数据
    input wire logic [p_width-1:0] i_data1, // 索引为一的权重列数据
    input wire logic [p_width-1:0] i_data2, // 索引为二的权重列数据
    input wire logic [p_width-1:0] i_data3, // 索引为三的权重列数据
    output logic [p_width-1:0] o_data // 选择后的输出数据
);
    assign o_data = i_select[1] ? (i_select[0] ? i_data3 : i_data2) :
        (i_select[0] ? i_data1 : i_data0);
endmodule

`default_nettype wire
