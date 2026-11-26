// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 定宽条件加一，各位依据分组进位条件并行计算。
module conditional_increment #(
    parameter int unsigned p_width = 28,
    parameter int unsigned p_group_width = 4,
    parameter bit p_native_groups = 1'b0 // 每组采用普通定宽加法形成结果。
) (
    input wire logic [p_width-1:0] i_value, // 参与定宽运算的数值
    input wire logic i_enable, // 条件步进使能
    output logic [p_width-1:0] o_result // 按定宽回绕后的运算结果
);
    localparam int unsigned p_groups = (p_width+p_group_width-1)/p_group_width;
    (* keep = 1 *) logic [p_groups-1:0] group_propagate;
    (* keep = 1 *) logic [p_groups-1:0] lower_groups_propagate;
    logic [p_width-1:0] binary_result;
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = group*p_group_width;
        localparam int unsigned p_count = p_width-p_first < p_group_width ?
            p_width-p_first : p_group_width;
        assign group_propagate[group] = &i_value[p_first+:p_count];
        if (group == 0) begin : g_first
            assign lower_groups_propagate[group] = 1'b1;
        end else begin : g_remaining
            all_reduce #(.p_width(group)) u_lower_groups (
                .i_value(group_propagate[group-1:0]), .o_all(lower_groups_propagate[group])
            );
        end
        if (p_native_groups) begin : g_native
            assign binary_result[p_first+:p_count] = i_value[p_first+:p_count] +
                p_count'(i_enable && lower_groups_propagate[group]);
        end else begin : g_parallel
            for (genvar item = 0; item < p_count; item++) begin : g_item
                logic local_propagate;
                if (item == 0) begin : g_first
                    assign local_propagate = 1'b1;
                end else begin : g_remaining
                    assign local_propagate = &i_value[p_first+:item];
                end
                assign binary_result[p_first+item] = i_value[p_first+item] ^
                    (i_enable && lower_groups_propagate[group] && local_propagate);
            end
        end
    end
    always_comb begin
        case (^{i_value, i_enable})
            1'b0, 1'b1: o_result = binary_result;
            default: o_result = i_value+p_width'(i_enable);
        endcase
    end
endmodule

`default_nettype wire
