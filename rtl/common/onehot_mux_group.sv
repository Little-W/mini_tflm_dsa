// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 对一组已选候选位执行与或归并。
module onehot_mux_group #(
    parameter int unsigned p_count = 3
) (
    input  wire logic [p_count-1:0] i_select, // 候选数据选择条件
    input  wire logic [p_count-1:0] i_data, // 各候选数据
    output logic o_data // 选择后的输出数据
);
    assign o_data = |(i_select & i_data);
endmodule

`default_nettype wire
