// SPDX-License-Identifier: Apache-2.0
`default_nettype none

// 比较配置接收前后的分块坐标，配置使能只参与最终相等结果的选择。
module ia_ordered_coordinate_update #(
    parameter int unsigned p_width = 32,
    parameter int unsigned p_low_width = 4
) (
    input  wire logic i_update, // 本周期接收新的坐标基值。
    input  wire logic [p_width-1:0] i_base, // 当前保存的坐标基值。
    input  wire logic [p_width-1:0] i_next_base, // 配置提供的新坐标基值。
    input  wire logic [p_width-1:0] i_offset, // 两个坐标共同使用的请求偏移量。
    output logic o_equal // 接收配置前后的坐标属于同一个分块。
);
    localparam int unsigned p_high_width = p_width - p_low_width;
    logic update_equal;
    logic [p_width-1:0] selected_base;
    logic selected_equal;

    // 当前坐标和新坐标并行比较，未接收配置时沿用当前分块。
    ia_ordered_coordinate_same #(
        .p_width(p_width), .p_low_width(p_low_width)
    ) u_updated_coordinate (
        .i_base_a(i_base), .i_base_b(i_next_base), .i_offset(i_offset),
        .o_equal(update_equal)
    );
    assign selected_base = i_update ? i_next_base : i_base;

`ifdef SYNTHESIS
    logic [1:0] selected_low_carry;
    logic [2:0] selected_high_equal;
    if (p_low_width > 0) begin : g_low_carry
        logic [1:0][p_low_width-1:0] unused_sum;
        assign {selected_low_carry[0], unused_sum[0]} =
            {1'b0, i_base[p_low_width-1:0]} + {1'b0, i_offset[p_low_width-1:0]};
        assign {selected_low_carry[1], unused_sum[1]} =
            {1'b0, selected_base[p_low_width-1:0]} + {1'b0, i_offset[p_low_width-1:0]};
    end else begin : g_no_low_carry
        assign selected_low_carry = '0;
    end
    assign selected_high_equal[0] =
        i_base[p_width-1:p_low_width] == selected_base[p_width-1:p_low_width];
    add_equal #(.p_width(p_high_width)) u_selected_base_advanced (
        .i_a(i_base[p_width-1:p_low_width]), .i_b(p_high_width'(0)),
        .i_target(selected_base[p_width-1:p_low_width]), .i_carry_in(1'b1),
        .o_equal(selected_high_equal[1])
    );
    add_equal #(.p_width(p_high_width)) u_selected_next_advanced (
        .i_a(selected_base[p_width-1:p_low_width]), .i_b(p_high_width'(0)),
        .i_target(i_base[p_width-1:p_low_width]), .i_carry_in(1'b1),
        .o_equal(selected_high_equal[2])
    );
    assign selected_equal = (selected_low_carry[0] == selected_low_carry[1]) ?
        selected_high_equal[0] :
        (selected_low_carry[0] ? selected_high_equal[1] : selected_high_equal[2]);
`else
    logic [1:0][p_width-1:0] selected_sum;
    assign selected_sum[0] = i_base + i_offset;
    assign selected_sum[1] = selected_base + i_offset;
    assign selected_equal = selected_sum[0][p_width-1:p_low_width] ==
        selected_sum[1][p_width-1:p_low_width];
`endif

    // 含未知值的控制或坐标按完整的基值选择和坐标运算传播。
    always_comb begin
        case (^{i_update, i_base, i_next_base, i_offset})
            1'b0, 1'b1: o_equal = !i_update || update_equal;
            default: o_equal = selected_equal;
        endcase
    end
endmodule

`default_nettype wire
