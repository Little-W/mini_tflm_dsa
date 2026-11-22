// SPDX-License-Identifier: Apache-2.0
// 分组检查置位数量，再以三叉组合树合并；全部输出均为当前周期的组合结果。
`default_nettype none
module onehot_check #(
    parameter int p_width = 32,
    parameter bit p_allow_zero = 1'b0
) (
    input  wire logic [p_width-1:0] i_value,
    output logic o_valid
);
    //! 0. 分组尺寸与状态
    //! -----------------

    localparam int p_groups = (p_width + 4) / 5;
    localparam int p_levels = $clog2(p_groups) + 1;
    logic [p_groups-1:0] group_any [0:p_levels];
    logic [p_groups-1:0] group_multiple [0:p_levels];

    //! 1. 检查各组置位数量
    //! -------------------

    // 每组独立保存非零和至少两位置位两个条件，最高一组补零。
    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_leaf
        logic [4:0] value_group;

        assign value_group = 5'(i_value >> (5 * group_index));
        assign group_any[0][group_index] = |value_group;
        assign group_multiple[0][group_index] =
            (value_group[0] & (|value_group[4:1])) |
            (value_group[1] & (|value_group[4:2])) |
            (value_group[2] & (|value_group[4:3])) |
            (value_group[3] & value_group[4]);
    end

    //! 2. 合并分组并输出检查结果
    //! -------------------------

    // 三个子组并行合并；单个子组直接传递，不引入串行计数。
    for (genvar level = 1; level <= p_levels; level++) begin : g_level
        localparam int p_previous_span = 3 ** (level - 1);
        localparam int p_current_span = 3 ** level;
        localparam int p_previous_nodes = (p_groups + p_previous_span - 1) / p_previous_span;
        localparam int p_current_nodes = (p_groups + p_current_span - 1) / p_current_span;

        for (genvar node = 0; node < p_groups; node++) begin : g_node
            if (node < p_current_nodes) begin : g_active
                logic [2:0] child_any;
                logic [2:0] child_multiple;

                for (genvar child = 0; child < 3; child++) begin : g_child
                    if (3 * node + child < p_previous_nodes) begin : g_present
                        assign child_any[child] = group_any[level-1][3*node+child];
                        assign child_multiple[child] = group_multiple[level-1][3*node+child];
                    end else begin : g_empty
                        assign child_any[child] = 1'b0;
                        assign child_multiple[child] = 1'b0;
                    end
                end
                assign group_any[level][node] = |child_any;
                assign group_multiple[level][node] = (|child_multiple) |
                    (child_any[0] & child_any[1]) | (child_any[0] & child_any[2]) |
                    (child_any[1] & child_any[2]);
            end else begin : g_unused
                assign group_any[level][node] = 1'b0;
                assign group_multiple[level][node] = 1'b0;
            end
        end
    end
    assign o_valid = !group_multiple[p_levels][0] && (p_allow_zero || group_any[p_levels][0]);
endmodule
`default_nettype wire
