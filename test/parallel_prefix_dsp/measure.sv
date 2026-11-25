// SPDX-License-Identifier: Apache-2.0
module parallel_prefix_dsp_measure #(
    parameter int unsigned WIDTH = 32,
    parameter int unsigned SPLIT = 16,
    parameter int CARRY = -1
) (
    input  logic             i_clk,
    input  logic [WIDTH-1:0] i_a,
    input  logic [WIDTH-1:0] i_b,
    input  logic             i_carry,
    output logic [WIDTH:0]   o_sum
);
    logic [WIDTH-1:0] saved_a, saved_b;
    logic saved_carry, selected_carry;
    logic [WIDTH:0] result;

    assign selected_carry = CARRY < 0 ? saved_carry : CARRY != 0;
    parallel_prefix_add #(
        .p_width(WIDTH), .p_group_width(8), .p_preserve_groups(1'b1),
        .p_carry_select_width(16), .p_dsp_split_width(SPLIT)
    ) u_sum (
        .i_a(saved_a), .i_b(saved_b), .i_carry(selected_carry),
        .o_sum(result[WIDTH-1:0]), .o_carry(result[WIDTH])
    );
    always_ff @(posedge i_clk) begin
        saved_a <= i_a;
        saved_b <= i_b;
        saved_carry <= i_carry;
        o_sum <= result;
    end
endmodule
