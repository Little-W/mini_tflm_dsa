// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 三个候选位分别受选择位控制，并行归并为一个输出位。
(* keep_hierarchy = "yes" *)
module onehot_mux_group #(
    parameter int unsigned p_count = 3
) (
    input  wire logic [p_count-1:0] i_select,
    input  wire logic [p_count-1:0] i_data,
    output logic o_data
);
    assign o_data = |(i_select & i_data);
endmodule

// 分组计算独热选择，每组结果完成后统一归并。
(* keep_hierarchy = "yes" *)
module onehot_mux #(
    parameter int unsigned p_choices = 8,
    parameter int unsigned p_width = 1
) (
    input  wire logic [p_choices-1:0] i_select,
    input  wire logic [p_choices-1:0][p_width-1:0] i_data,
    output logic [p_width-1:0] o_data
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
