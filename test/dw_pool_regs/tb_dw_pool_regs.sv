// SPDX-License-Identifier: Apache-2.0
module tb_dw_pool_regs;
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic [15:0] awaddr=0, araddr=0;
  logic awvalid=0, awready, wvalid=0, wready;
  logic [31:0] wdata=0, rdata;
  logic [3:0] wstrb=0;
  logic [1:0] bresp, rresp;
  logic bvalid, bready=0, arvalid=0, arready, rvalid, rready=0;
  logic calc_start, cfg_dw_enable, cfg_dw_vector_s16;
  logic [3:0] cfg_dw_op;
  logic [31:0] cfg_dw_length;
  logic ready=1, done=0, done_ready, busy, irq;
  logic [1:0] error=0;
  logic [31:0] status;
  integer starts=0, checks=0;

  npu_axil_reg_if #(.DW_POOL_CAPABLE(1), .DW_PE_COUNT(4), .DW_MAX_TAPS(49)) dut (
    .clk, .rst_n,
    .s_axil_awaddr(awaddr), .s_axil_awprot(3'b0), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
    .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
    .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
    .s_axil_araddr(araddr), .s_axil_arprot(3'b0), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
    .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
    .calc_start, .cfg_dw_enable, .cfg_dw_op, .cfg_dw_vector_s16, .cfg_dw_length,
    .dw_stat_cycles(32'd321), .dw_stat_compute(32'd27), .dw_stat_dma_wait(32'd201),
    .npu_sa_ready(ready), .npu_done_valid(done), .npu_done_ready(done_ready),
    .npu_err_code(error), .irq, .npu_busy(busy), .status_bits(status)
  );
  always @(posedge clk) if (rst_n && calc_start) starts<=starts+1;

  task automatic check(input logic condition, input string message);
    if (!condition) $fatal(1,"%s",message);
    checks++;
  endtask
  task automatic address(input logic [15:0] addr);
    @(negedge clk); awaddr=addr; awvalid=1;
    do @(posedge clk); while (!awready);
    @(negedge clk); awvalid=0;
  endtask
  task automatic data(input logic [31:0] value, input logic [3:0] mask);
    @(negedge clk); wdata=value; wstrb=mask; wvalid=1;
    do @(posedge clk); while (!wready);
    @(negedge clk); wvalid=0;
  endtask
  task automatic write_reg(input logic [15:0] addr, input logic [31:0] value,
                           input logic [3:0] mask, input logic [1:0] expected,
                           input bit data_first=0);
    if (data_first) begin data(value,mask); repeat(2) @(posedge clk); address(addr); end
    else begin address(addr); repeat(2) @(posedge clk); data(value,mask); end
    wait(bvalid); #1; check(bresp==expected,"write response");
    repeat(2) begin @(posedge clk); #1; check(bvalid && bresp==expected,"held write response"); end
    @(negedge clk); bready=1;
    @(posedge clk); @(negedge clk); bready=0;
  endtask
  task automatic read_reg(input logic [15:0] addr, output logic [31:0] value);
    @(negedge clk); araddr=addr; arvalid=1;
    do @(posedge clk); while (!arready);
    @(negedge clk); arvalid=0;
    wait(rvalid); #1; value=rdata; check(rresp==0,"read response");
    repeat(2) begin @(posedge clk); #1; check(rvalid && rdata==value,"held read response"); end
    @(negedge clk); rready=1;
    @(posedge clk); @(negedge clk); rready=0;
  endtask
  logic [31:0] value;
  initial begin
    repeat(5) @(negedge clk); rst_n=1;
    read_reg(16'h00b8,value); check(value==32'h0131040f,"capability fields");
    read_reg(16'h00bc,value); check(value==321,"cycle statistics");
    read_reg(16'h00c0,value); check(value==27,"compute statistics");
    read_reg(16'h00c4,value); check(value==201,"DMA wait statistics");
    write_reg(16'h0000,32'h00000100,4'b0010,0);
    read_reg(16'h0000,value); check(value[8] && !value[6],"DW selector byte write");
    write_reg(16'h00b0,32'h00000007,4'b0001,0,1);
    write_reg(16'h00b0,32'h000001ff,4'b0010,0);
    read_reg(16'h00b0,value); check(value==32'h00000107,"operation byte enables");
    write_reg(16'h00b4,32'h11223344,4'b1100,0);
    write_reg(16'h00b4,32'hffffabcd,4'b0011,0,1);
    read_reg(16'h00b4,value); check(value==32'h1122abcd,"length byte enables");
    write_reg(16'h0000,32'h00000111,4'b1111,0);
    check(busy && starts==1,"one accepted start");
    write_reg(16'h00b0,32'h00000000,4'b1111,2);
    write_reg(16'h00b4,32'h00000001,4'b1111,2,1);
    write_reg(16'h0000,32'h00000101,4'b1111,2);
    read_reg(16'h00b0,value); check(value==32'h00000107,"operation held while busy");
    read_reg(16'h00b4,value); check(value==32'h1122abcd,"length held while busy");
    check(starts==1,"duplicate start rejected");
    write_reg(16'h0004,32'h00000004,4'b0001,0);
    check(busy,"status clear preserves active task");
    @(negedge clk); done=1; error=2;
    @(negedge clk); done=0;
    read_reg(16'h0004,value); check(!value[1] && value[2] && value[4:3]==2,"completion and error status");
    check(irq,"completion interrupt");
    write_reg(16'h0004,32'h00000004,4'b0001,0);
    check(!irq,"interrupt clear");
    write_reg(16'h0000,32'h0,4'b1111,0);
    read_reg(16'h0000,value); check(!value[8],"return to matrix selector");
    ready=0;
    write_reg(16'h0000,32'h00000101,4'b1111,2);
    check(!busy && starts==1,"start rejected while core is unavailable");
    $display("DW_POOL_REGS_PASS checks=%0d starts=%0d",checks,starts);
    $finish;
  end
  initial begin #50000; $fatal(1,"register test timeout"); end
endmodule
