// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 六输入归并树：每一级仅依赖前一级的六个结果。
module ps_scheduler_any #(
    parameter int p_width = 16
) (
    input  wire logic [p_width-1:0] i_value,
    output logic o_any
);
    localparam int p_groups = (p_width + 5) / 6;
    localparam int p_levels = $clog2(p_groups) + 1;

    for (genvar level = 0; level <= p_levels; level++) begin : g_level
        localparam int p_span = 6 ** level;
        localparam int p_nodes = (p_width + p_span - 1) / p_span;
        localparam int p_previous_span = level > 0 ? 6 ** (level - 1) : 1;
        localparam int p_previous_nodes = (p_width + p_previous_span - 1) / p_previous_span;

        for (genvar node = 0; node < p_width; node++) begin : g_node
            logic any_set;

            if (level == 0) begin : g_input
                assign any_set = i_value[node];
            end else if (node == 0 && p_previous_nodes == 1) begin : g_pass
                assign any_set = g_level[level-1].g_node[0].any_set;
            end else if (node < p_nodes) begin : g_reduce
                logic [5:0] any_i_value;
                logic any_o_value;

                for (genvar child = 0; child < 6; child++) begin : g_child
                    if (6 * node + child < p_previous_nodes) begin : g_present
                        assign any_i_value[child] = g_level[level-1].g_node[6*node+child].any_set;
                    end else begin : g_empty
                        assign any_i_value[child] = 1'b0;
                    end
                end
                assign any_o_value = |any_i_value;
                assign any_set = any_o_value;
            end else begin : g_unused
                assign any_set = 1'b0;
            end
        end
    end
    assign o_any = g_level[p_levels].g_node[0].any_set;
endmodule

`default_nettype wire
