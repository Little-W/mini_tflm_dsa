`timescale 1ns/1ps
// Directed reset-phase check against the production clock gate. Other NPU
// interfaces are intentionally inactive; the full transaction test is separate.
module tb_clock_gate_reset;
`ifdef XILINX_FPGA
  glbl glbl();
`endif
  logic clk=0, rst_n=0;
  always #5 clk=~clk;
  npu_axil_top #(.SIZE(2), .ENABLE_VECTOR_ENGINE(0), .ENABLE_CLOCK_GATING(1)) dut
    (.clk(clk), .rst_n(rst_n), .m_axi_rvalid(1'b0), .m_axi_bvalid(1'b0));
  int edges=0;
  time last_rise;
  bit saw_rise=0;
  always @(posedge dut.npu_core_clk) begin
    if (clk !== 1'b1 || ($time % 10) != 5)
      $fatal(1,"partial or unexpected clock pulse at %0t", $time);
    edges++;
    last_rise=$time;
    saw_rise=1;
  end
  always @(negedge dut.npu_core_clk)
    if (saw_rise && $time-last_rise != 5)
      $fatal(1,"short or extended high pulse at %0t",$time);
  initial begin
    // Isolate gate protocol from unconnected AXI/control and NPU outputs.
    force dut.calc_start_pulse=0;
    force dut.npu_busy=0;
    force dut.npu_axi_idle=1;
    force dut.npu_sa_ready=1;
    force dut.npu_done_valid=0;
    force dut.npu_done_ready=0;
    // Official glbl holds GSR for 100 ns: maintain reset beyond its release.
    repeat (15) @(negedge clk);
    #1 rst_n=1;
    repeat (5) @(negedge clk);
    #1;
    if (dut.npu_core_clk !== 0 || dut.npu_clk_gate_en !== 0)
      $fatal(1,"gate did not enter idle");
    // Assert reset midway through a high phase while the clock is gated.
    @(posedge clk); #2 rst_n=0; #1;
    if (dut.npu_core_clk !== 0) $fatal(1,"reset created a high-phase edge");
    @(negedge clk); #1;
    if (dut.npu_core_clk !== 0) $fatal(1,"clock not low");
    @(posedge clk); #1;
    if (dut.npu_core_clk !== 1) $fatal(1,"reset did not reopen clock");
    @(negedge clk); #1 rst_n=1;
    repeat (5) @(negedge clk); #1;
    if (dut.npu_clk_gate_en !== 0) $fatal(1,"warmup did not expire");
    // Repeat reset while the source clock is low and verify recovery.
    @(negedge clk); #1 rst_n=0; #1;
    if (dut.npu_core_clk !== 0) $fatal(1,"low-phase reset raised clock");
    @(posedge clk); #1;
    if (dut.npu_core_clk !== 1) $fatal(1,"low-phase reset did not reopen clock");
    @(negedge clk); #1 rst_n=1;
    repeat (5) @(negedge clk); #1;
    if (dut.npu_clk_gate_en !== 0) $fatal(1,"low-phase reset did not recover idle");
    // A request asserted in a high phase must not create an early edge;
    // it is retained across the wakeup interval and delivered once ready.
    @(posedge clk); #1 force dut.calc_start_pulse=1; #1;
    if (dut.npu_core_clk !== 0) $fatal(1,"start created a high-phase edge");
    @(negedge clk); @(posedge clk); #1;
    force dut.calc_start_pulse=0;
    if (!dut.npu_start_pending_q || !dut.npu_start_warmup_q)
      $fatal(1,"start not retained during warmup");
    @(posedge clk); #1;
    if (!dut.npu_core_calc_start) $fatal(1,"start not delivered after warmup");
    @(posedge clk); #1;
    if (dut.npu_core_calc_start) $fatal(1,"start delivered more than once");
    force dut.npu_done_valid=1;
    force dut.npu_done_ready=1;
    @(posedge clk); #1;
    force dut.npu_done_valid=0;
    force dut.npu_done_ready=0;
    // Completion must not close the gate while an AXI response is draining.
    force dut.npu_axi_idle=0;
    repeat (5) @(posedge clk);
    #1;
    if (!dut.npu_clk_gate_en || !dut.npu_clk_req_q)
      $fatal(1,"gate closed before AXI drain");
    force dut.npu_axi_idle=1;
    repeat (4) @(negedge clk); #1;
    if (dut.npu_clk_gate_en !== 0) $fatal(1,"completion did not close gate");
    $display("CLOCK_GATE_RESET_PASS edges=%0d",edges);
    $finish;
  end
endmodule
