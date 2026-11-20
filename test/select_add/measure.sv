// SPDX-License-Identifier: Apache-2.0
module select_add_reference (
    input logic clk,
    input logic signed [31:0] i_acc,
    input logic signed [31:0] i_ws_bias,
    input logic signed [31:0] i_is_bias,
    input logic i_is_mode,
    input logic i_ws_final,
    output logic signed [31:0] o_value
);
    logic signed [31:0] acc_q, ws_bias_q, is_bias_q;
    logic is_mode_q, ws_final_q;
    logic signed [31:0] result;
    always_ff @(posedge clk) begin
        acc_q <= i_acc;
        ws_bias_q <= i_ws_bias;
        is_bias_q <= i_is_bias;
        is_mode_q <= i_is_mode;
        ws_final_q <= i_ws_final;
        o_value <= result;
    end
    assign result = is_mode_q ? acc_q + is_bias_q :
                    ws_final_q ? acc_q + ws_bias_q : acc_q;
endmodule

module select_add_candidate (
    input logic clk,
    input logic signed [31:0] i_acc,
    input logic signed [31:0] i_ws_bias,
    input logic signed [31:0] i_is_bias,
    input logic i_is_mode,
    input logic i_ws_final,
    output logic signed [31:0] o_value
);
    logic signed [31:0] acc_q, ws_bias_q, is_bias_q;
    logic is_mode_q, ws_final_q;
    logic signed [31:0] result;
    always_ff @(posedge clk) begin
        acc_q <= i_acc;
        ws_bias_q <= i_ws_bias;
        is_bias_q <= i_is_bias;
        is_mode_q <= i_is_mode;
        ws_final_q <= i_ws_final;
        o_value <= result;
    end
    select_add #(.p_width(32)) u_add (
        .i_lhs(acc_q), .i_rhs0(ws_bias_q), .i_rhs1(is_bias_q),
        .i_rhs_select(is_mode_q), .i_add_enable(is_mode_q || ws_final_q), .o_sum(result)
    );
endmodule
