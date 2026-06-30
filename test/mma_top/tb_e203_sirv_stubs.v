`timescale 1ns/1ps

module sirv_gnrl_dffr #(
  parameter int DW = 1
) (
  input  wire [DW-1:0] dnxt,
  output reg  [DW-1:0] qout,
  input  wire          clk,
  input  wire          rst_n
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) qout <= '0;
    else        qout <= dnxt;
  end
endmodule

module sirv_gnrl_dffl #(
  parameter int DW = 1
) (
  input  wire          lden,
  input  wire [DW-1:0] dnxt,
  output reg  [DW-1:0] qout,
  input  wire          clk
);
  always_ff @(posedge clk) begin
    if (lden) qout <= dnxt;
  end
endmodule

module sirv_gnrl_dfflr #(
  parameter int DW = 1
) (
  input  wire          lden,
  input  wire [DW-1:0] dnxt,
  output reg  [DW-1:0] qout,
  input  wire          clk,
  input  wire          rst_n
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)     qout <= '0;
    else if (lden) qout <= dnxt;
  end
endmodule

module sirv_gnrl_dfflrs #(
  parameter int DW = 1
) (
  input  wire          lden,
  input  wire [DW-1:0] dnxt,
  output reg  [DW-1:0] qout,
  input  wire          clk,
  input  wire          rst_n
);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n)     qout <= {DW{1'b1}};
    else if (lden) qout <= dnxt;
  end
endmodule

module e203_clkgate (
  input  wire clk_in,
  input  wire test_mode,
  input  wire clock_en,
  output wire clk_out
);
  assign clk_out = clk_in & (clock_en | test_mode);
endmodule
