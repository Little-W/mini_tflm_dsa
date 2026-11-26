// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 将一拍窗口的有效元素数加入完整接收计数，高位传播条件与低位加法并行计算。
(* keep_hierarchy = "yes" *)
module vector_window_count_add #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_increment_width = 4
) (
    input wire logic [p_width-1:0] i_value, // 当前已接收元素数，保留完整定宽回绕行为。
    input wire logic [p_increment_width-1:0] i_increment, // 本拍窗口返回的有效元素数量。
    output logic [p_width-1:0] o_sum // 加入本拍元素数后的接收计数。
);
    logic [p_width-1:0] complete_sum;
    logic unused_complete_carry;

    parallel_prefix_add #(.p_width(p_width)) u_complete_sum (
        .i_a(i_value), .i_b(p_width'(i_increment)), .i_carry(1'b0),
        .o_sum(complete_sum), .o_carry(unused_complete_carry)
    );
    if (p_increment_width < p_width) begin : g_split
        localparam int unsigned p_high_width = p_width-p_increment_width;
        localparam int unsigned p_high_groups = (p_high_width+3)/4;
        logic [p_increment_width:0] low_sum;
        logic [p_high_groups-1:0] high_group_all;
        logic [p_width-1:0] selected_sum;

        // 低段最高进位采用并行产生条件，低位和值仍由普通定宽算术推断。
        parallel_prefix_add #(.p_width(p_increment_width)) u_low_sum (
            .i_a(i_value[p_increment_width-1:0]), .i_b(i_increment), .i_carry(1'b0),
            .o_sum(low_sum[p_increment_width-1:0]), .o_carry(low_sum[p_increment_width])
        );
        assign selected_sum[p_increment_width-1:0] = low_sum[p_increment_width-1:0];
        // 高段每四位独立归约，组前缀仅依赖旧计数并提前形成。
        // 前缀归并保持独立组合边界，低段进位只进入各组的末级修正。
        for (genvar group_index=0; group_index<p_high_groups; group_index++) begin : g_group
            localparam int unsigned p_first = group_index*4;
            localparam int unsigned p_bits = p_high_width-p_first < 4 ? p_high_width-p_first : 4;
            (* keep = group_index < p_high_groups-1 *) logic group_all;
            logic preceding_propagate;

            assign group_all = &i_value[p_increment_width+p_first+:p_bits];
            assign high_group_all[group_index] = group_all;
            if (group_index == 0) begin : g_first
                assign preceding_propagate = 1'b1;
            end else begin : g_later
                (* keep_hierarchy = "yes" *) add_equal_reduce #(.p_width(group_index)) u_prefix (
                    .i_equal(high_group_all[group_index-1:0]), .o_equal(preceding_propagate)
                );
            end
            vector_window_count_group #(.p_bits(p_bits)) u_correction (
                .i_prefix(preceding_propagate),
                .i_sum(i_value[p_increment_width+p_first+:p_bits]),
                .i_carry(low_sum[p_increment_width]),
                .o_sum(selected_sum[p_increment_width+p_first+:p_bits])
            );
        end
        always_comb begin
            case (^{i_value, i_increment})
                1'b0, 1'b1: o_sum = selected_sum;
                default: o_sum = complete_sum;
            endcase
        end
    end else begin : g_full_width
        assign o_sum = complete_sum;
    end
endmodule

`default_nettype wire
