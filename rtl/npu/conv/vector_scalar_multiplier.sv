// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module vector_scalar_multiplier (
  input  wire logic clk,
  input  wire logic signed [31:0] a,
  input  wire logic signed [31:0] b,
  output logic signed [63:0] product
);
  //! 0. Helper
  //! ---------

  (* use_dsp = "yes" *) logic [31:0] low_product;
  (* use_dsp = "yes" *) logic signed [32:0] low_high_product;
  (* use_dsp = "yes" *) logic signed [32:0] high_low_product;
  (* use_dsp = "yes" *) logic signed [31:0] high_product;
  logic [47:0] diagonal, low_high_extended, high_low_extended;
  logic [47:0] compressed_sum, compressed_carry;
  (* use_dsp = "no" *) logic [47:0] upper_sum;

  //! 1. Capture Partial Products
  //! ---------------------------

  // The low halves are unsigned; the high halves retain the INT32 signs.
  always_ff @(posedge clk) begin
    low_product      <= a[15:0] * b[15:0];
    low_high_product <= $signed({1'b0,a[15:0]}) * $signed(b[31:16]);
    high_low_product <= $signed(a[31:16]) * $signed({1'b0,b[15:0]});
    high_product     <= $signed(a[31:16]) * $signed(b[31:16]);
  end

  //! 2. Assemble Registered Product
  //! ------------------------------

  // The diagonal terms occupy disjoint bit positions. Carry-save compression
  // reduces the three upper terms to one 48-bit carry-propagating addition.
  assign diagonal          = {high_product,low_product[31:16]};
  assign low_high_extended = {{15{low_high_product[32]}},low_high_product};
  assign high_low_extended = {{15{high_low_product[32]}},high_low_product};
  assign compressed_sum    = diagonal ^ low_high_extended ^ high_low_extended;
  assign compressed_carry  = ((diagonal & low_high_extended) |
                             (diagonal & high_low_extended) |
                             (low_high_extended & high_low_extended)) << 1;
  assign upper_sum         = compressed_sum + compressed_carry;

  // Inputs sampled at E0 produce this register at E1 for consumption at E2.
  always_ff @(posedge clk) begin
    product <= {upper_sum,low_product[15:0]};
  end
endmodule

`default_nettype wire
