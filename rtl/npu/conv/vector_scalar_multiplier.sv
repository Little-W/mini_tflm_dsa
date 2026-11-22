// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vector_scalar_multiplier (
    input  wire logic clk,
    input  wire logic signed [31:0] a,
    input  wire logic signed [31:0] b,
    output logic signed [63:0] product
);
    registered_multiplier_s32 u_multiplier (
        .clk(clk), .i_en(1'b1), .i_a(a), .i_b(b), .o_product(product)
    );
endmodule

`default_nettype wire
