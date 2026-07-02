`timescale 1ns / 1ps

`ifndef XILINX_CLK_WIZ_IP
module clk_wiz_0 (
    output wire clk_out1,
    input  wire reset,
    output wire locked,
    input  wire clk_in1
);

    assign clk_out1 = clk_in1;
    assign locked   = ~reset;

endmodule
`endif
