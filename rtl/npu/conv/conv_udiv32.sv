// SPDX-License-Identifier: Apache-2.0
// Unsigned restoring divider: only used at tile initialization, never per MAC.
module conv_udiv32 (
  input logic clk, rst_n, start,
  input logic [31:0] dividend, divisor,
  output logic busy, done, div_zero,
  output logic [31:0] quotient, remainder
);
  logic [31:0] numer, denom, q;
  logic [32:0] rem, shifted;
  logic [5:0] count;
  always_comb shifted = {rem[31:0], numer[31]};
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      busy <= 0; done <= 0; div_zero <= 0;
      quotient <= 0; remainder <= 0;
      numer <= 0; denom <= 0; q <= 0; rem <= 0; count <= 0;
    end else begin
      done <= 0;
      if (start && !busy) begin
        div_zero <= (divisor == 0);
        if (divisor == 0) begin
          quotient <= '1; remainder <= dividend; done <= 1;
        end else begin
          numer <= dividend; denom <= divisor; q <= 0; rem <= 0;
          count <= 32; busy <= 1;
        end
      end else if (busy) begin
        numer <= {numer[30:0],1'b0};
        if (shifted >= {1'b0,denom}) begin
          rem <= shifted - {1'b0,denom};
          q <= {q[30:0],1'b1};
        end else begin
          rem <= shifted;
          q <= {q[30:0],1'b0};
        end
        count <= count - 1'b1;
        if (count == 1) begin
          busy <= 0; done <= 1;
          quotient <= {q[30:0], (shifted >= {1'b0,denom})};
          remainder <= (shifted >= {1'b0,denom}) ?
                       32'(shifted - {1'b0,denom}) : shifted[31:0];
        end
      end
    end
  end
endmodule
