`timescale 1ns/1ps
module sram_case #(
  parameter integer DEPTH = 128,
  parameter integer AW = 7,
  parameter integer FORCE_MACRO_DEPTH = 0
)(output logic done = 0);
  logic clk = 0;
  logic we = 0, re = 0;
  logic [AW-1:0] wa = 0, ra = 0;
  logic [18:0] wd = 0, mask = 0;
  wire [18:0] q;
  wire [31:0] selected_depth, selected_banks;
  logic [18:0] reference [0:DEPTH-1];
  logic [18:0] last_read = 'x;
  integer checks = 0;
  always #5 clk = ~clk;

  if (FORCE_MACRO_DEPTH > 0) begin : g_explicit
    smic40_sram_1r1w #(.DATA_WIDTH(19), .DEPTH(DEPTH), .ADDR_WIDTH(AW),
      .MACRO_DEPTH(FORCE_MACRO_DEPTH)) u_storage
      (.clk(clk), .write_enable(we), .write_address(wa), .write_data(wd), .write_mask(mask),
       .read_enable(re), .read_address(ra), .read_data(q));
    assign selected_depth = u_storage.MACRO_DEPTH;
    assign selected_banks = u_storage.BANKS;
  end else begin : g_default
    smic40_sram_1r1w #(.DATA_WIDTH(19), .DEPTH(DEPTH), .ADDR_WIDTH(AW)) u_storage
      (.clk(clk), .write_enable(we), .write_address(wa), .write_data(wd), .write_mask(mask),
       .read_enable(re), .read_address(ra), .read_data(q));
    assign selected_depth = u_storage.MACRO_DEPTH;
    assign selected_banks = u_storage.BANKS;
  end

  task automatic transfer(input logic write_en, read_en, input integer write_addr, read_addr,
                          input logic [18:0] value, write_mask);
    @(negedge clk);
    we = write_en; re = read_en; wa = AW'(write_addr); ra = AW'(read_addr);
    wd = value; mask = write_mask;
    if (read_en) last_read = reference[read_addr];
    if (write_en) begin
      for (integer bit_index = 0; bit_index < 19; bit_index++) begin
        if (write_mask[bit_index]) reference[write_addr][bit_index] = value[bit_index];
      end
    end
    @(posedge clk); #1;
    if (q !== last_read)
      $fatal(1, "DEPTH=%0d macro=%0d addr=%0d actual=%h expected=%h", DEPTH, selected_depth, read_addr, q, last_read);
    checks++;
  endtask

  initial begin
    integer expected_depth;
    #1;
    expected_depth = FORCE_MACRO_DEPTH > 0 ? FORCE_MACRO_DEPTH : (DEPTH <= 384 ? 128 : 1024);
    if (selected_depth != expected_depth || selected_banks != (DEPTH + expected_depth - 1) / expected_depth)
      $fatal(1, "Unexpected SRAM macro selection DEPTH=%0d", DEPTH);
    for (integer address = 0; address < DEPTH; address++)
      transfer(1, 0, address, 0, 19'((address * 769) ^ 19'h51234), '1);
    // 全部逻辑地址均覆盖部分写入和相邻地址并行读取，跨越每个物理深度分组。
    for (integer address = 0; address < DEPTH; address++)
      transfer(1, 1, address, (address + 1) % DEPTH,
               19'((address * 1021) ^ 19'h56abf), 19'h15555);
    for (integer address = 0; address < DEPTH; address++)
      transfer(0, 1, 0, address, 0, 0);
    transfer(1, 0, DEPTH-1, 0, 19'h7xxxx, 19'h0000f);
    transfer(0, 1, 0, DEPTH-1, 0, 0);
    repeat (4) transfer(0, 0, 0, 0, 0, 0);
    $display("SRAM_CASE_PASS depth=%0d macro_depth=%0d banks=%0d explicit=%0d checks=%0d",
             DEPTH, selected_depth, selected_banks, FORCE_MACRO_DEPTH, checks);
    done = 1;
  end
endmodule

module tb_sram_1r1w;
  wire [6:0] done;
  sram_case #(.DEPTH(128), .AW(7)) u_depth128(done[0]);
  sram_case #(.DEPTH(256), .AW(8)) u_depth256(done[1]);
  sram_case #(.DEPTH(384), .AW(9)) u_depth384(done[2]);
  sram_case #(.DEPTH(385), .AW(9)) u_depth385(done[3]);
  sram_case #(.DEPTH(1100), .AW(11)) u_depth1100(done[4]);
  sram_case #(.DEPTH(256), .AW(8), .FORCE_MACRO_DEPTH(1024)) u_explicit1024(done[5]);
  sram_case #(.DEPTH(512), .AW(9), .FORCE_MACRO_DEPTH(128)) u_explicit128(done[6]);
  initial begin
    wait (&done);
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
