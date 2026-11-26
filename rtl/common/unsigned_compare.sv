// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 并行比较无符号操作数的各个位段，按最高不相等位段决定完整次序。
// FPGA 的宽比较使用两段普通减法，由工具推断算术资源。
module unsigned_compare #(
    parameter int unsigned p_width = 32,
    parameter bit p_split_compare = 1'b1
) (
    input  wire logic [p_width-1:0] i_a /* 第一输入操作数。 */,
    input  wire logic [p_width-1:0] i_b /* 第二输入操作数。 */,
    output logic o_less /* 第一无符号操作数小于第二操作数。 */,
    output logic o_equal /* 两个输入操作数相等。 */
);
    localparam int unsigned p_groups = (p_width + 7) / 8;
    logic [p_groups-1:0] group_less, group_equal;
    logic [p_groups-1:0] group_greater;
    logic [p_groups-1:0] selected_less;
    logic reference_less, reference_equal;

    // 每组独立形成大小与相等关系，只有所有更高分组相等时才选中本组。
    for (genvar group = 0; group < p_groups; group++) begin : g_group
        localparam int unsigned p_first = group * 8;
        localparam int unsigned p_bits = p_width-p_first < 8 ? p_width-p_first : 8;
        assign group_less[group] = i_a[p_first+:p_bits] < i_b[p_first+:p_bits];
        assign group_equal[group] = i_a[p_first+:p_bits] == i_b[p_first+:p_bits];
        assign group_greater[group] = !group_less[group] && !group_equal[group];
        if (group == p_groups - 1) begin : g_highest
            assign selected_less[group] = group_less[group];
        end else begin : g_lower
            assign selected_less[group] = group_less[group] &&
                (&group_equal[p_groups-1:group+1]);
        end
    end
    // 已知输入直接归并各组结果；未知输入沿完整关系向量传播四态语义。
    always_comb begin
        case (^{i_a, i_b})
            1'b0, 1'b1: reference_less = |selected_less;
            default: reference_less = group_less > group_greater;
        endcase
    end
    assign reference_equal = &group_equal;

`ifdef XILINX_FPGA
    if (p_split_compare && p_width >= 24 && p_width <= 46) begin : g_split_compare
        localparam int unsigned p_low_width = p_width / 2;
        localparam int unsigned p_high_width = p_width - p_low_width;
        localparam int unsigned p_low_groups = (p_low_width + 5) / 6;
        localparam int unsigned p_high_groups = (p_high_width + 5) / 6;
        logic [p_low_width:0] low_difference;
        logic [p_high_width:0] high_difference;
        logic [p_low_groups-1:0] low_zero;
        logic [p_high_groups-1:0] high_zero;
        logic high_equal, low_equal, less;

        // 各段先扩展零位；减法结果的最高位即该段的无符号借位。
        parallel_prefix_native_differences #(
            .p_low_width(p_low_width + 1), .p_high_width(p_high_width + 1)
        ) u_difference (
            .i_low_a({1'b0, i_a[p_low_width-1:0]}),
            .i_low_b({1'b0, i_b[p_low_width-1:0]}),
            .i_high_a({1'b0, i_a[p_width-1:p_low_width]}),
            .i_high_b({1'b0, i_b[p_width-1:p_low_width]}),
            .o_low_difference(low_difference), .o_high_difference(high_difference)
        );
        // 差值按六位独立检查零值，最后同时合并大小关系和相等关系。
        for (genvar group_index = 0; group_index < p_low_groups; group_index++) begin : g_low_zero
            localparam int unsigned p_first = group_index * 6;
            localparam int unsigned p_bits = p_low_width - p_first < 6 ? p_low_width - p_first : 6;
            zero_reduce #(.p_width(p_bits)) u_zero (
                .i_value(low_difference[p_first+:p_bits]), .o_zero(low_zero[group_index])
            );
        end
        for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high_zero
            localparam int unsigned p_first = group_index * 6;
            localparam int unsigned p_bits = p_high_width - p_first < 6 ? p_high_width - p_first : 6;
            zero_reduce #(.p_width(p_bits)) u_zero (
                .i_value(high_difference[p_first+:p_bits]), .o_zero(high_zero[group_index])
            );
        end
        assign high_equal = &high_zero;
        assign low_equal = &low_zero;
        assign less = high_difference[p_high_width] |
            (high_equal & low_difference[p_low_width]);

        // 输入含未知位时沿原分组关系传播，完整保留相等与大小比较的四态结果。
        always_comb begin
            case (^{i_a, i_b})
                1'b0, 1'b1: begin
                    o_less = less;
                    o_equal = high_equal & low_equal;
                end
                default: begin
                    o_less = reference_less;
                    o_equal = reference_equal;
                end
            endcase
        end
    end else begin : g_group_compare
        assign {o_less, o_equal} = {reference_less, reference_equal};
    end
`else
    assign {o_less, o_equal} = {reference_less, reference_equal};
`endif
endmodule

`default_nettype wire
