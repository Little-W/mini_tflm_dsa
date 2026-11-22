// SPDX-License-Identifier: Apache-2.0
module select_add_formal #(
    parameter int p_width = 32
) (
    input logic signed [p_width-1:0] i_lhs,
    input logic signed [p_width-1:0] i_rhs0,
    input logic signed [p_width-1:0] i_rhs1,
    input logic i_rhs_select,
    input logic i_add_enable
);
    logic signed [p_width-1:0] actual_sum;
    logic signed [p_width-1:0] bias_sum;
    logic signed [p_width:0] exact_sum;
    logic signed [p_width-1:0] selected_rhs;
    logic signed [p_width-1:0] reference_bias_sum;

    select_add #(.p_width(p_width)) u_sum (
        .i_lhs(i_lhs), .i_rhs0(i_rhs0), .i_rhs1(i_rhs1),
        .i_rhs_select(i_rhs_select), .i_add_enable(i_add_enable), .o_sum(actual_sum)
    );
    select_add #(.p_width(p_width)) u_bias (
        .i_lhs(i_lhs), .i_rhs0(i_rhs0), .i_rhs1(i_rhs1),
        .i_rhs_select(i_rhs_select), .i_add_enable(i_rhs_select || i_add_enable), .o_sum(bias_sum)
    );

    // 完整扩展一位求和，再截取低位，覆盖正负数及模加溢出。
    assign selected_rhs = i_rhs_select ? i_rhs1 : i_rhs0;
    assign exact_sum = $signed({i_lhs[p_width-1], i_lhs}) +
                       $signed({selected_rhs[p_width-1], selected_rhs});
    assign reference_bias_sum = i_rhs_select ? i_lhs + i_rhs1 :
                                i_add_enable ? i_lhs + i_rhs0 : i_lhs;
    always_comb begin
        assert(actual_sum == (i_add_enable ? exact_sum[p_width-1:0] : i_lhs));
        assert(bias_sum == reference_bias_sum);
    end
endmodule
