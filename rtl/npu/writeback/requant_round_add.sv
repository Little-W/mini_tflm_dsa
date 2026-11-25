// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 低段舍入进位与高段修正分别展开，保留完整的三十五位量化结果。
(* keep_hierarchy = "yes" *)
module requant_round_add #(
    parameter int unsigned p_width = 35,
    parameter int unsigned p_low_width = 18
) (
    input wire logic [p_width-1:0] i_a, i_b,
    input wire logic i_increment,
    output logic [p_width-1:0] o_sum
);
    localparam int unsigned p_high_width = p_width - p_low_width;
    localparam int unsigned p_low_groups = (p_low_width + 3) / 4;
    localparam int unsigned p_high_groups = (p_high_width + 3) / 4;
    logic [p_low_width:0] low_sum;
    logic [p_high_width-1:0] high_sum;
    logic [p_low_groups-1:0] low_group_all;
    logic [p_high_groups-1:0] high_group_all;
    logic high_increment;
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
    assign high_increment = low_sum[p_low_width] |
        (i_increment & (&low_group_all));
    for (genvar bit_index = 0; bit_index < p_low_width; bit_index++) begin : g_low_bit
        localparam int unsigned p_groups = bit_index / 4;
        localparam int unsigned p_bits = bit_index % 4;
        logic lower_all, local_all;
        if (p_groups == 0) begin : g_first_group
            assign lower_all = 1'b1;
        end else begin : g_lower_groups
            assign lower_all = &low_group_all[p_groups-1:0];
        end
        if (p_bits == 0) begin : g_first_bit
            assign local_all = 1'b1;
        end else begin : g_lower_bits
            assign local_all = &low_sum[p_groups*4+:p_bits];
        end
        assign calculated_sum[bit_index] = low_sum[bit_index] ^ (i_increment & lower_all & local_all);
    end
    for (genvar bit_index = 0; bit_index < p_high_width; bit_index++) begin : g_high_bit
        localparam int unsigned p_groups = bit_index / 4;
        localparam int unsigned p_bits = bit_index % 4;
        logic lower_all, local_all;
        if (p_groups == 0) begin : g_first_group
            assign lower_all = 1'b1;
        end else begin : g_lower_groups
            assign lower_all = &high_group_all[p_groups-1:0];
        end
        if (p_bits == 0) begin : g_first_bit
            assign local_all = 1'b1;
        end else begin : g_lower_bits
            assign local_all = &high_sum[p_groups*4+:p_bits];
        end
        assign calculated_sum[p_low_width+bit_index] = high_sum[bit_index] ^
            (high_increment & lower_all & local_all);
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
