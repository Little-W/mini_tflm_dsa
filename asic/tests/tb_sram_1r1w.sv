`timescale 1ns/1ps
module sram_case #(parameter DEPTH=128, AW=7)(output reg done=0);
  reg clk=0, we=0, re=0;
  reg [AW-1:0] wa=0, ra=0;
  reg [18:0] wd=0, mask=0;
  wire [18:0] q;
  always #5 clk=~clk;
  smic40_sram_1r1w #(.DATA_WIDTH(19), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) dut
    (.clk(clk),.write_enable(we),.write_address(wa),.write_data(wd),.write_mask(mask),
     .read_enable(re),.read_address(ra),.read_data(q));
  initial begin
    @(negedge clk); we=1; wa=DEPTH-1; wd=19'h51234; mask='1;
    @(negedge clk); we=0; re=1; ra=DEPTH-1;
    @(negedge clk); if (q !== 19'h51234) $fatal(1,"DEPTH=%0d read %h",DEPTH,q);
    re=0; we=1; mask=19'h00ff0; wd=19'h56abf;
    @(negedge clk); we=0; re=1;
    @(negedge clk); if (q !== 19'h51ab4) $fatal(1,"DEPTH=%0d masked read %h",DEPTH,q);
    re=0; we=1; wa=3; wd=19'h30123; mask='1;
    @(negedge clk); re=1; ra=DEPTH-1; we=1; wa=3; wd=19'h20321;
    @(negedge clk); if (q !== 19'h51ab4) $fatal(1,"DEPTH=%0d concurrent read %h",DEPTH,q);
    we=0; re=1; ra=3;
    @(negedge clk); if (q !== 19'h20321) $fatal(1,"DEPTH=%0d second address %h",DEPTH,q);
    done=1;
  end
endmodule
module tb_sram_1r1w;
  wire done_a,done_b;
  sram_case #(.DEPTH(128),.AW(7)) a(done_a);
  sram_case #(.DEPTH(1100),.AW(11)) b(done_b);
  initial begin
    wait(done_a && done_b);
    $display("SRAM macro tests passed");
    $finish;
  end
endmodule

module tb_ia_buffer;
  reg clk=0, rst_n=0, wr_en=0, rd_en=0;
  reg [6:0] wr_addr=0, rd_addr=0;
  reg [31:0] wr_data=0;
  reg [3:0] wr_mask=0;
  wire [31:0] rd_data;
  always #5 clk=~clk;
  ia_buffer_wrapper dut(.clk(clk),.rst_n(rst_n),.wr_en(wr_en),.wr_addr(wr_addr),
    .wr_data(wr_data),.wr_mask(wr_mask),.rd_en(rd_en),.rd_addr(rd_addr),.rd_data(rd_data));
  initial begin
    @(posedge clk); #1; if (rd_data !== 0) $fatal(1,"reset read value");
    @(negedge clk); rst_n=1; wr_en=1; wr_addr=4; wr_data=32'h12345678; wr_mask=4'hf;
    @(negedge clk); wr_en=0; rd_en=1; rd_addr=4;
    @(negedge clk); if (rd_data !== 32'h12345678) $fatal(1,"read value %h",rd_data);
    rd_en=0; wr_en=1; wr_data=32'habcd0123; wr_mask=4'b0101;
    @(negedge clk); wr_en=0; rd_en=1;
    @(negedge clk); if (rd_data !== 32'h12cd5623) $fatal(1,"masked read %h",rd_data);
    rst_n=0; #1; if (rd_data !== 0) $fatal(1,"reset after read");
    $display("IA buffer macro test passed"); $finish;
  end
endmodule
