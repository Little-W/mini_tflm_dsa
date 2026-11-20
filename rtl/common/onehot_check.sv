// SPDX-License-Identifier: Apache-2.0
// 分组检查置位数量，再以三叉组合树合并；全部输出均为当前周期的组合结果。
`default_nettype none
module onehot_check #(
    parameter int p_width = 32,
    parameter bit p_allow_zero = 1'b0,
    parameter bit p_use_lut =
`ifdef ASIC_SYNTHESIS
        1'b0
`elsif XILINX_FPGA
        1'b1
`else
        1'b0
`endif
) (
    input  logic [p_width-1:0] i_value,
    output logic o_valid
);
    //! 0. 分组尺寸与查找表
    //! -------------------

    localparam int p_groups = (p_width + 4) / 5;
    localparam int p_levels = $clog2(p_groups) + 1;
    localparam logic [63:0] p_leaf_flags = 64'hfffe_fee8_ffff_fffe;
    localparam logic [63:0] p_leaf_valid = p_allow_zero ?
        64'h0001_0117_0001_0117 : 64'h0001_0116_0001_0116;
    localparam logic [63:0] p_pair_flags = 64'hffec_ffec_fafa_fafa;
    localparam logic [63:0] p_triple_any = 64'hffff_fafa_ffff_fafa;
    localparam logic [63:0] p_triple_multiple = 64'hffff_ffff_fffe_ffec;
    localparam logic [63:0] p_root_valid = p_allow_zero ?
        64'h0000_0000_0001_0013 : 64'h0000_0000_0001_0012;

    //! 1. 五位输入分组
    //! ---------------

    for (genvar group_index = 0; group_index < p_groups; group_index++) begin : g_leaf
        logic group_any;
        logic group_multiple;
        logic [4:0] check_i_value;
        logic leaf_any;
        logic leaf_multiple;

        assign check_i_value = 5'(i_value >> (5 * group_index));
        assign leaf_any = |check_i_value;
        assign leaf_multiple =
            (check_i_value[0] & (|check_i_value[4:1])) |
            (check_i_value[1] & (|check_i_value[4:2])) |
            (check_i_value[2] & (|check_i_value[4:3])) |
            (check_i_value[3] & check_i_value[4]);

        if (p_groups == 1) begin : g_root
            if (p_use_lut) begin : g_lut
                logic check_o_valid;

                LUT6 #(.INIT(p_leaf_valid)) u_check (
                    .I0(check_i_value[0]), .I1(check_i_value[1]),
                    .I2(check_i_value[2]), .I3(check_i_value[3]),
                    .I4(check_i_value[4]), .I5(1'b0),
                    .O(check_o_valid)
                );
                assign o_valid = check_o_valid;
            end else begin : g_logic
                assign o_valid = !leaf_multiple && (p_allow_zero || leaf_any);
            end
            assign group_any = 1'b0;
            assign group_multiple = 1'b0;
        end else if (p_use_lut) begin : g_lut
            logic check_o_any;
            logic check_o_multiple;

            // I5 固定为一，使两个输出分别采用查找表的两个三十二位区域。
            LUT6_2 #(.INIT(p_leaf_flags)) u_check (
                .I0(check_i_value[0]), .I1(check_i_value[1]),
                .I2(check_i_value[2]), .I3(check_i_value[3]),
                .I4(check_i_value[4]), .I5(1'b1),
                .O5(check_o_any), .O6(check_o_multiple)
            );
            assign group_any = check_o_any;
            assign group_multiple = check_o_multiple;
        end else begin : g_logic
            assign group_any = leaf_any;
            assign group_multiple = leaf_multiple;
        end
    end

    //! 2. 合并分组结果
    //! ---------------

    // 每个节点只记录非零和至少两位置位，保持逻辑层数随输入宽度对数增长。
    for (genvar level = 1; level <= p_levels; level++) begin : g_level
        localparam int p_previous_span = 3 ** (level - 1);
        localparam int p_current_span = 3 ** level;
        localparam int p_previous_nodes = (p_groups + p_previous_span - 1) / p_previous_span;
        localparam int p_current_nodes = (p_groups + p_current_span - 1) / p_current_span;

        for (genvar node = 0; node < p_groups; node++) begin : g_node
            logic group_any;
            logic group_multiple;

            if (p_previous_nodes > 1 && node < p_current_nodes) begin : g_active
                localparam int p_children = p_previous_nodes - 3 * node >= 3 ?
                    3 : p_previous_nodes - 3 * node;
                logic [5:0] check_i_flags;
                logic any_set;
                logic multiple_set;

                for (genvar child = 0; child < 3; child++) begin : g_child
                    if (child < p_children) begin : g_present
                        if (level == 1) begin : g_leaf_source
                            assign check_i_flags[2*child] = g_leaf[3*node+child].group_any;
                            assign check_i_flags[2*child+1] = g_leaf[3*node+child].group_multiple;
                        end else begin : g_node_source
                            assign check_i_flags[2*child] = g_level[level-1].g_node[3*node+child].group_any;
                            assign check_i_flags[2*child+1] = g_level[level-1].g_node[3*node+child].group_multiple;
                        end
                    end else begin : g_empty
                        assign check_i_flags[2*child +: 2] = 2'b00;
                    end
                end
                assign any_set = check_i_flags[0] | check_i_flags[2] | check_i_flags[4];
                assign multiple_set = check_i_flags[1] | check_i_flags[3] | check_i_flags[5] |
                    (check_i_flags[0] & check_i_flags[2]) |
                    (check_i_flags[0] & check_i_flags[4]) |
                    (check_i_flags[2] & check_i_flags[4]);

                if (p_current_nodes == 1) begin : g_root
                    if (p_use_lut) begin : g_lut
                        logic check_o_valid;

                        LUT6 #(.INIT(p_root_valid)) u_check (
                            .I0(check_i_flags[0]), .I1(check_i_flags[1]),
                            .I2(check_i_flags[2]), .I3(check_i_flags[3]),
                            .I4(check_i_flags[4]), .I5(check_i_flags[5]),
                            .O(check_o_valid)
                        );
                        assign o_valid = check_o_valid;
                    end else begin : g_logic
                        assign o_valid = !multiple_set && (p_allow_zero || any_set);
                    end
                    assign group_any = 1'b0;
                    assign group_multiple = 1'b0;
                end else if (p_children == 1) begin : g_pass
                    assign group_any = check_i_flags[0];
                    assign group_multiple = check_i_flags[1];
                end else if (p_use_lut && p_children == 2) begin : g_pair
                    logic check_o_any;
                    logic check_o_multiple;

                    LUT6_2 #(.INIT(p_pair_flags)) u_check (
                        .I0(check_i_flags[0]), .I1(check_i_flags[1]),
                        .I2(check_i_flags[2]), .I3(check_i_flags[3]),
                        .I4(1'b0), .I5(1'b1),
                        .O5(check_o_any), .O6(check_o_multiple)
                    );
                    assign group_any = check_o_any;
                    assign group_multiple = check_o_multiple;
                end else if (p_use_lut) begin : g_triple
                    logic [5:0] any_i_flags;
                    logic [5:0] multiple_i_flags;
                    logic any_o_value;
                    logic multiple_o_value;

                    assign any_i_flags = check_i_flags;
                    assign multiple_i_flags = check_i_flags;

                    LUT6 #(.INIT(p_triple_any)) u_any (
                        .I0(any_i_flags[0]), .I1(any_i_flags[1]),
                        .I2(any_i_flags[2]), .I3(any_i_flags[3]),
                        .I4(any_i_flags[4]), .I5(any_i_flags[5]),
                        .O(any_o_value)
                    );
                    LUT6 #(.INIT(p_triple_multiple)) u_multiple (
                        .I0(multiple_i_flags[0]), .I1(multiple_i_flags[1]),
                        .I2(multiple_i_flags[2]), .I3(multiple_i_flags[3]),
                        .I4(multiple_i_flags[4]), .I5(multiple_i_flags[5]),
                        .O(multiple_o_value)
                    );
                    assign group_any = any_o_value;
                    assign group_multiple = multiple_o_value;
                end else begin : g_logic
                    assign group_any = any_set;
                    assign group_multiple = multiple_set;
                end
            end else begin : g_unused
                assign group_any = 1'b0;
                assign group_multiple = 1'b0;
            end
        end
    end
endmodule
`default_nettype wire
