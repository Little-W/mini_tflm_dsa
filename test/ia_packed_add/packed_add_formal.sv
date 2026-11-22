// 比较四组独立操作数与四通道分段加法，输入不施加取值约束。
module packed_add_formal #(
    parameter int p_lane_width = 8
) (
    input logic [4*p_lane_width-1:0] i_lhs,
    input logic [4*p_lane_width-1:0] i_rhs0,
    input logic [4*p_lane_width-1:0] i_rhs1,
    input logic i_rhs_select,
    input logic i_add_enable,
    output logic o_equivalent,
    output logic o_padding_zero
);
    logic signed [47:0] packed_lhs, packed_rhs0, packed_rhs1, packed_sum;
    logic [4*p_lane_width-1:0] expected, actual;
    logic [3:0] padding_zero;

    for (genvar lane = 0; lane < 4; lane++) begin : g_lane
        assign packed_lhs[lane*12 +: 12] = 12'(i_lhs[lane*p_lane_width +: p_lane_width]);
        assign packed_rhs0[lane*12 +: 12] = 12'(i_rhs0[lane*p_lane_width +: p_lane_width]);
        assign packed_rhs1[lane*12 +: 12] = 12'(i_rhs1[lane*p_lane_width +: p_lane_width]);
        assign actual[lane*p_lane_width +: p_lane_width] = packed_sum[lane*12 +: p_lane_width];
        logic [p_lane_width:0] reference_sum;
        logic [p_lane_width-1:0] reference_rhs;
        assign reference_rhs = i_rhs_select ? i_rhs1[lane*p_lane_width +: p_lane_width] :
                                             i_rhs0[lane*p_lane_width +: p_lane_width];
        assign reference_sum = {1'b0, i_lhs[lane*p_lane_width +: p_lane_width]} +
                               {1'b0, reference_rhs};
        assign expected[lane*p_lane_width +: p_lane_width] = i_add_enable ?
            reference_sum[p_lane_width-1:0] : i_lhs[lane*p_lane_width +: p_lane_width];
        if (p_lane_width == 8) begin : g_byte_padding
            assign padding_zero[lane] = packed_sum[lane*12+9 +: 3] == 3'd0;
        end else begin : g_full_lane
            assign padding_zero[lane] = 1'b1;
        end
    end
    select_add #(.p_width(48), .p_split_12bit(1'b1)) u_packed (
        .i_lhs(packed_lhs), .i_rhs0(packed_rhs0), .i_rhs1(packed_rhs1),
        .i_rhs_select(i_rhs_select), .i_add_enable(i_add_enable), .o_sum(packed_sum)
    );
    assign o_equivalent = actual == expected;
    assign o_padding_zero = &padding_zero;
endmodule

// 恢复加法保留完整有符号范围，并在输出端扩展到 16 位阵列数据。
module restore_add_formal #(
    parameter int p_offset_width = 9
) (
    input logic [31:0] i_bytes,
    input logic [p_offset_width-1:0] i_offset,
    output logic o_equivalent
);
    localparam int p_sum_width = ((p_offset_width > 8) ? p_offset_width : 8) + 1;
    logic signed [47:0] packed_lhs, packed_rhs, packed_sum;
    logic [63:0] expected, actual;
    for (genvar lane = 0; lane < 4; lane++) begin : g_lane
        logic signed [p_sum_width:0] byte_extended, offset_extended;
        logic signed [p_sum_width-1:0] scalar_sum;
        logic unused_carry;
        assign byte_extended = (p_sum_width+1)'($signed(i_bytes[lane*8 +: 8]));
        assign offset_extended = (p_sum_width+1)'($signed(i_offset));
        assign {unused_carry, scalar_sum} = byte_extended + offset_extended;
        assign expected[lane*16 +: 16] = 16'($signed(scalar_sum));
        assign packed_lhs[lane*12 +: 12] = 12'($signed(i_bytes[lane*8 +: 8]));
        assign packed_rhs[lane*12 +: 12] = 12'($signed(i_offset));
        assign actual[lane*16 +: 16] = 16'($signed(packed_sum[lane*12 +: p_sum_width]));
    end
    select_add #(.p_width(48), .p_split_12bit(1'b1)) u_packed (
        .i_lhs(packed_lhs), .i_rhs0(packed_rhs), .i_rhs1(packed_rhs),
        .i_rhs_select(1'b0), .i_add_enable(1'b1), .o_sum(packed_sum)
    );
    assign o_equivalent = actual == expected;
endmodule
