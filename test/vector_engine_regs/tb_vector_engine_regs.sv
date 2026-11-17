// SPDX-License-Identifier: Apache-2.0
module tb_vector_engine_regs #(parameter bit CAPABLE=1, parameter int POOL_LIMIT=256);
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  logic [15:0] awaddr=0, araddr=0;
  logic awvalid=0, awready, wvalid=0, wready;
  logic [31:0] wdata=0, rdata;
  logic [3:0] wstrb=0;
  logic [1:0] bresp, rresp;
  logic bvalid, bready=0, arvalid=0, arready, rvalid, rready=0;
  logic calc_start, cfg_vector_enable, cfg_vector_s16;
  logic [3:0] cfg_vector_op;
  logic [31:0] cfg_vector_length;
  logic signed [31:0] cfg_add_input1_multiplier, cfg_add_input1_shift;
  logic signed [31:0] cfg_add_input2_multiplier, cfg_add_input2_shift, cfg_add_left_shift;
  logic signed [31:0] lhs_zp, rhs_zp, q_mult_pt, q_shift_pt, dst_zp, act_min, act_max;
  logic ready=1, done=0, done_ready, busy, irq;
  logic [1:0] error=0;
  logic [31:0] status;
  integer starts=0, checks=0;

  npu_axil_reg_if #(
`ifdef VECTOR_REGS_LEGACY_PARAMETERS
    .DW_POOL_CAPABLE(CAPABLE), .DW_PE_COUNT(4),
`else
    .DW_POOL_CAPABLE(!CAPABLE), .DW_PE_COUNT(2),
    .VECTOR_ENGINE_CAPABLE(CAPABLE), .VECTOR_PE_COUNT(4),
`endif
    .DW_MAX_TAPS(49), .POOL_MAX_TAPS(POOL_LIMIT)) dut (
    .clk, .rst_n,
    .s_axil_awaddr(awaddr), .s_axil_awprot(3'b0), .s_axil_awvalid(awvalid), .s_axil_awready(awready),
    .s_axil_wdata(wdata), .s_axil_wstrb(wstrb), .s_axil_wvalid(wvalid), .s_axil_wready(wready),
    .s_axil_bresp(bresp), .s_axil_bvalid(bvalid), .s_axil_bready(bready),
    .s_axil_araddr(araddr), .s_axil_arprot(3'b0), .s_axil_arvalid(arvalid), .s_axil_arready(arready),
    .s_axil_rdata(rdata), .s_axil_rresp(rresp), .s_axil_rvalid(rvalid), .s_axil_rready(rready),
    .calc_start, .cfg_vector_enable, .cfg_vector_op, .cfg_vector_s16, .cfg_vector_length,
    .cfg_add_input1_multiplier, .cfg_add_input1_shift,
    .cfg_add_input2_multiplier, .cfg_add_input2_shift, .cfg_add_left_shift,
    .lhs_zp, .rhs_zp, .q_mult_pt, .q_shift_pt, .dst_zp, .act_min, .act_max,
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
  logic [31:0] add_values [5] = '{32'h40000000,32'hffffffe1,32'h60000000,32'd0,32'd22};
  initial begin
    repeat(5) @(negedge clk); rst_n=1;
    read_reg(16'h00b8,value); check(value==(CAPABLE ? 32'h0131047f : 32'd0),"capability fields");
    read_reg(16'h00c8,value); check(value==(CAPABLE ? 32'(POOL_LIMIT) : 32'd0),"pool window capacity");
    write_reg(16'h00c8,32'hffffffff,4'b1111,0);
    read_reg(16'h00c8,value); check(value==(CAPABLE ? 32'(POOL_LIMIT) : 32'd0),"pool capacity read-only");
    read_reg(16'h00bc,value); check(value==0,"reserved cycle register");
    read_reg(16'h00c0,value); check(value==0,"reserved compute register");
    read_reg(16'h00c4,value); check(value==0,"reserved DMA wait register");
    for (int i=0;i<5;i++) begin
      read_reg(16'h00cc+16'(4*i),value); check(value==0,"Add parameter reset");
      write_reg(16'h00cc+16'(4*i),32'ha1b2c3d4,4'b1100,0);
      write_reg(16'h00cc+16'(4*i),32'h1020c3d4,4'b0011,0,1);
      read_reg(16'h00cc+16'(4*i),value); check(value==32'ha1b2c3d4,"Add parameter byte enables");
      write_reg(16'h00cc+16'(4*i),32'hffffffff,4'b0000,0);
      read_reg(16'h00cc+16'(4*i),value); check(value==32'ha1b2c3d4,"Add zero strobe preserves parameter");
      write_reg(16'h00cc+16'(4*i),add_values[i],4'b1111,0);
      read_reg(16'h00cc+16'(4*i),value); check(value==add_values[i],"Add parameter full write");
    end
    check(cfg_add_input1_multiplier==32'sh40000000 && cfg_add_input1_shift==-31 &&
          cfg_add_input2_multiplier==32'sh60000000 && cfg_add_input2_shift==0 &&
          cfg_add_left_shift==22,"Add parameter output ports");
    write_reg(16'h0038,32'hffffff81,4'b1111,0);
    write_reg(16'h003c,32'd128,4'b1111,0);
    write_reg(16'h0040,32'd127,4'b1111,0);
    write_reg(16'h0044,32'h7fffffff,4'b1111,0);
    write_reg(16'h0048,32'd30,4'b1111,0);
    write_reg(16'h004c,32'hffffff80,4'b1111,0);
    write_reg(16'h0050,32'd127,4'b1111,0);
    check(lhs_zp==-127 && rhs_zp==128 && dst_zp==127 &&
          q_mult_pt==32'sh7fffffff && q_shift_pt==30 && act_min==-128 && act_max==127,
          "Add shared scalar parameters");
    write_reg(16'h0000,32'h00000100,4'b0010,0);
    read_reg(16'h0000,value); check(value[8] && !value[6],"VCE selector byte write");
    write_reg(16'h00b0,32'h00000007,4'b0001,0,1);
    write_reg(16'h00b0,32'h000001ff,4'b0010,0);
    read_reg(16'h00b0,value); check(value==32'h00000107,"operation byte enables");
    write_reg(16'h00b4,32'h11223344,4'b1100,0);
    write_reg(16'h00b4,32'hffffabcd,4'b0011,0,1);
    read_reg(16'h00b4,value); check(value==32'h1122abcd,"length byte enables");
    write_reg(16'h00b0,32'd9,4'b1111,0);
    read_reg(16'h00b0,value); check(value==9 && cfg_vector_op==9 && !cfg_vector_s16,"INT8 Add operation");
    write_reg(16'h0000,32'h00000111,4'b1111,0);
    check(busy && starts==1,"one accepted start");
    write_reg(16'h00b0,32'h00000000,4'b1111,2);
    write_reg(16'h00b4,32'h00000001,4'b1111,2,1);
    write_reg(16'h0000,32'h00000101,4'b1111,2);
    read_reg(16'h00b0,value); check(value==9,"operation held while busy");
    read_reg(16'h00b4,value); check(value==32'h1122abcd,"length held while busy");
    for (int i=0;i<5;i++) begin
      write_reg(16'h00cc+16'(4*i),32'h0,4'b1111,2);
      read_reg(16'h00cc+16'(4*i),value); check(value==add_values[i],"Add parameter held while busy");
    end
    write_reg(16'h0038,32'd0,4'b1111,2);
    write_reg(16'h003c,32'd0,4'b1111,2);
    write_reg(16'h0044,32'd0,4'b1111,2);
    write_reg(16'h0048,32'd0,4'b1111,2);
    check(lhs_zp==-127 && rhs_zp==128 && q_mult_pt==32'sh7fffffff && q_shift_pt==30,
          "Add shared parameters held while busy");
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
    $display("VECTOR_ENGINE_REGS_PASS checks=%0d starts=%0d",checks,starts);
    $finish;
  end
  initial begin #50000; $fatal(1,"register test timeout"); end
endmodule
