// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 按各选择位屏蔽候选数据，并分组归并所有候选位。
module onehot_mux #(
    parameter int unsigned p_choices = 8,
    parameter int unsigned p_width = 1
) (
    input  wire logic [p_choices-1:0] i_select, // 候选数据选择条件
    input  wire logic [p_choices-1:0][p_width-1:0] i_data, // 各候选数据
    output logic [p_width-1:0] o_data // 选择后的输出数据
);
    localparam int unsigned p_groups = (p_choices+2)/3;
    for (genvar bit_index = 0; bit_index < p_width; bit_index++) begin : g_bit
        logic [p_groups-1:0] group_data;
        for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_group
            localparam int unsigned p_count = p_choices-3*group_index < 3 ?
                p_choices-3*group_index : 3;
            logic [p_count-1:0] candidates;
            for (genvar item = 0; item < p_count; item++) begin : g_item
                assign candidates[item] = i_data[3*group_index+item][bit_index];
            end
            onehot_mux_group #(.p_count(p_count)) u_group (
                .i_select(i_select[3*group_index+:p_count]), .i_data(candidates),
                .o_data(group_data[group_index])
            );
        end
        assign o_data[bit_index] = |group_data;
    end
endmodule

`default_nettype wire
