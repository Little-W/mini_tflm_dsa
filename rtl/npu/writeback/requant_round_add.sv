// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 对量化商、输出零点和舍入位求完整定宽和；分组并行计算低段与高段进位。
(* keep_hierarchy = "yes" *)
module requant_round_add #(
    parameter int unsigned p_width = 35,
    parameter int unsigned p_low_width = 18
) (
    input wire logic [p_width-1:0] i_a, // 量化商的完整有符号扩展位值
    input wire logic [p_width-1:0] i_b, // 输出零点偏移的完整有符号扩展位值
    input wire logic i_increment, // 当前舍入要求加入的一位增量
    output logic [p_width-1:0] o_sum // 包含舍入增量的完整定宽加法结果
);
    localparam int unsigned p_high_width = p_width - p_low_width;
    localparam int unsigned p_low_groups = (p_low_width + 3) / 4;
    localparam int unsigned p_high_groups = (p_high_width + 3) / 4;
    logic [p_low_width:0] low_sum;
    logic [p_high_width-1:0] high_sum;
    logic [p_low_groups-1:0] low_group_all;
    logic [p_high_groups-1:0] high_group_all;
    logic high_increment;
    logic low_all;
    logic [p_width-1:0] calculated_sum;

    // 两个普通加法输出供综合工具推断并行算术资源，输入保持原始位值。
    parallel_prefix_native_sums #(
        .p_low_width(p_low_width+1), .p_high_width(p_high_width)
    ) u_sums (
        .i_low_a({1'b0, i_a[p_low_width-1:0]}),
        .i_low_b({1'b0, i_b[p_low_width-1:0]}),
        .i_high_a(i_a[p_width-1:p_low_width]),
        .i_high_b(i_b[p_width-1:p_low_width]),
        .o_low_sum(low_sum), .o_high_sum(high_sum)
    );
    for (genvar group_index = 0; group_index < p_low_groups; group_index++) begin : g_low_group
        localparam int unsigned p_first = group_index * 4;
        localparam int unsigned p_bits = (p_low_width - p_first < 4) ? p_low_width - p_first : 4;
        (* keep = 1 *) logic all_bits;
        assign all_bits = &low_sum[p_first+:p_bits];
        assign low_group_all[group_index] = all_bits;
    end
    for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high_group
        localparam int unsigned p_first = group_index * 4;
        localparam int unsigned p_bits = (p_high_width - p_first < 4) ? p_high_width - p_first : 4;
        (* keep = 1 *) logic all_bits;
        assign all_bits = &high_sum[p_first+:p_bits];
        assign high_group_all[group_index] = all_bits;
    end
    // 各组前缀直接归并，进入高段的进位不逐组串行传播。
    (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(p_low_groups)) u_low_prefix (
        .i_equal(low_group_all), .o_equal(low_all)
    );
    assign high_increment = low_sum[p_low_width] | (i_increment & low_all);
    // 每个四位组独立修正，组内前缀最多三位，组间使用已归并的传播条件。
    for (genvar group_index = 0; group_index < p_low_groups; group_index++) begin : g_low_correction
        localparam int unsigned p_first = group_index * 4;
        localparam int unsigned p_bits = p_low_width - p_first < 4 ? p_low_width - p_first : 4;
        logic previous_all;
        if (group_index == 0) begin : g_first
            assign previous_all = 1'b1;
        end else begin : g_prefix
            (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(group_index)) u_all (
                .i_equal(low_group_all[group_index-1:0]), .o_equal(previous_all)
            );
        end
        for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
            logic local_all;
            if (bit_index == 0) assign local_all = 1'b1;
            else assign local_all = &low_sum[p_first+:bit_index];
            assign calculated_sum[p_first+bit_index] = low_sum[p_first+bit_index] ^
                (i_increment & previous_all & local_all);
        end
    end
    for (genvar group_index = 0; group_index < p_high_groups; group_index++) begin : g_high_correction
        localparam int unsigned p_first = group_index * 4;
        localparam int unsigned p_bits = p_high_width - p_first < 4 ? p_high_width - p_first : 4;
        logic previous_all;
        if (group_index == 0) begin : g_first
            assign previous_all = 1'b1;
        end else begin : g_prefix
            (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(group_index)) u_all (
                .i_equal(high_group_all[group_index-1:0]), .o_equal(previous_all)
            );
        end
        for (genvar bit_index = 0; bit_index < p_bits; bit_index++) begin : g_bit
            logic local_all;
            if (bit_index == 0) assign local_all = 1'b1;
            else assign local_all = &high_sum[p_first+:bit_index];
            assign calculated_sum[p_low_width+p_first+bit_index] = high_sum[p_first+bit_index] ^
                (high_increment & previous_all & local_all);
        end
    end
    always_comb begin
        o_sum = calculated_sum;
`ifndef SYNTHESIS
        case (^{i_a, i_b, i_increment})
            1'b0, 1'b1: begin end
            default: o_sum = i_a + i_b + p_width'(i_increment);
        endcase
`endif
    end
endmodule

`default_nettype wire
