// SPDX-License-Identifier: Apache-2.0
// One shared signed multiply/add/compare datapath. Arithmetic wraps at 32 bits.
module dw_pool_pe (
  input logic [2:0] op,
  input logic signed [15:0] a, b,
  input logic signed [31:0] acc,
  output logic signed [31:0] result
);
  logic signed [31:0] product, extended_a;
  assign product = a * b;
  assign extended_a = {{16{a[15]}},a};
  always_comb begin
    case (op)
      3'd0: result = acc + product;
      3'd1: result = acc + extended_a;
      3'd2: result = (acc > extended_a) ? acc : extended_a;
      3'd3: result = (acc < extended_a) ? acc : extended_a;
      3'd4: result = product;
      default: result = acc;
    endcase
  end
endmodule
