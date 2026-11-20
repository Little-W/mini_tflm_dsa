// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vector_scalar_multiplier #(
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1
`else
    parameter bit p_use_dsp = 1'b0
`endif
) (
    input  wire logic clk,
    input  wire logic signed [31:0] a,
    input  wire logic signed [31:0] b,
    output logic signed [63:0] product
);
    registered_multiplier_s32 #(.p_use_dsp(p_use_dsp)) u_multiplier (
        .clk(clk), .i_en(1'b1), .i_a(a), .i_b(b), .o_product(product)
    );
endmodule

// Each input register is independently optional; all stages share the enable.
module registered_multiplier_s32 #(
    parameter bit p_input_register = 1'b0,
    parameter bit p_b_input_register = p_input_register,
`ifdef ASIC_SYNTHESIS
    parameter bit p_use_dsp = 1'b0
`elsif XILINX_FPGA
    parameter bit p_use_dsp = 1'b1
`elsif SYNTHESIS
    parameter bit p_use_dsp = 1'b1
`else
    parameter bit p_use_dsp = 1'b0
`endif
) (
    input  wire logic clk,
    input  wire logic i_en,
    input  wire logic signed [31:0] i_a,
    input  wire logic signed [31:0] i_b,
    output logic signed [63:0] o_product
);
    logic signed [31:0] operand_a, operand_b;

    generate
        if (!p_input_register) begin : g_direct_a
            assign operand_a = i_a;
        end else begin : g_registered_a
            always_ff @(posedge clk) begin
                if (i_en) operand_a <= i_a;
            end
        end
        if (!p_b_input_register) begin : g_direct_b
            assign operand_b = i_b;
        end else begin : g_registered_b
            always_ff @(posedge clk) begin
                if (i_en) operand_b <= i_b;
            end
        end
    endgenerate

    // p_use_dsp remains an interface parameter. Multipliers are inferred so
    // technology mapping is left to synthesis rather than primitive instances.
    (* keep, use_dsp = "yes" *) logic [31:0] low_product;
    (* keep, use_dsp = "yes" *) logic signed [32:0] low_high_product;
    (* keep, use_dsp = "yes" *) logic signed [32:0] high_low_product;
    (* keep, use_dsp = "yes" *) logic signed [31:0] high_product;
    logic [47:0] diagonal;
    logic [47:0] low_high_extended, high_low_extended;
    logic [47:0] compressed_sum, compressed_carry;
    (* use_dsp = "no" *) logic [47:0] upper_sum;

    assign diagonal = {high_product, low_product[31:16]};

    always_ff @(posedge clk) begin
        if (i_en) begin
            low_product      <= operand_a[15:0] * operand_b[15:0];
            low_high_product <= $signed({1'b0, operand_a[15:0]}) * $signed(operand_b[31:16]);
            high_low_product <= $signed(operand_a[31:16]) * $signed({1'b0, operand_b[15:0]});
            high_product     <= $signed(operand_a[31:16]) * $signed(operand_b[31:16]);
        end
    end

    assign low_high_extended = {{15{low_high_product[32]}}, low_high_product};
    assign high_low_extended = {{15{high_low_product[32]}}, high_low_product};
    assign compressed_sum    = diagonal ^ low_high_extended ^ high_low_extended;
    assign compressed_carry  = ((diagonal & low_high_extended) |
                                (diagonal & high_low_extended) |
                                (low_high_extended & high_low_extended)) << 1;
    assign upper_sum = compressed_sum + compressed_carry;

    always_ff @(posedge clk) begin
        if (i_en) o_product <= {upper_sum, low_product[15:0]};
    end
endmodule
`default_nettype wire
