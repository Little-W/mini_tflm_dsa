// SPDX-License-Identifier: Apache-2.0
// One 16-bit multiplier supports signed MAC and full-width product assembly.
module vector_pe (
  input logic [2:0] op,
  input logic signed [15:0] a, b,
  input logic signed [31:0] acc,
  output logic signed [31:0] result
);
  logic [31:0] product_uu, product_su;
  logic signed [31:0] product_ss, extended_a;
  assign product_uu = $unsigned(a) * $unsigned(b);
  assign product_su = product_uu - (a[15] ? {b,16'b0} : 32'd0);
  assign product_ss = $signed(product_su - (b[15] ? {a,16'b0} : 32'd0));
  assign extended_a = {{16{a[15]}},a};
  always_comb begin
    case (op)
      3'd0: result = acc + product_ss;
      3'd1: result = acc + extended_a;
      3'd2: result = (acc > extended_a) ? acc : extended_a;
      3'd3: result = (acc < extended_a) ? acc : extended_a;
      3'd4: result = product_ss;
      3'd5: result = $signed(product_uu);
      3'd6: result = $signed(product_su);
      default: result = acc;
    endcase
  end
endmodule
