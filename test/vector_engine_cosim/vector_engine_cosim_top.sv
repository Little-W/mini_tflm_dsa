// SPDX-License-Identifier: Apache-2.0
// Test-only second AXI master loads/checks the unmodified production SoC RAM.
// The CPU-side production driver uses the actual NPU AXI-Lite slave below.
module vector_engine_cosim_top #(
  parameter int SIZE=16,
  parameter int VECTOR_PE_COUNT=8,
  parameter int ENABLE_VECTOR_ENGINE=1,
  parameter int ENABLE_PER_CHANNEL=1,
  parameter int ENABLE_IS_MODE=1,
  parameter int WEIGHT_WIDTH=16,
  parameter int RAM_WORDS=131072
)(
  input logic clk,rst_n,
  input logic [15:0] s_axil_awaddr,
  input logic s_axil_awvalid,
  output wire s_axil_awready,
  input logic [31:0] s_axil_wdata,
  input logic [3:0] s_axil_wstrb,
  input logic s_axil_wvalid,
  output wire s_axil_wready,
  output wire [1:0] s_axil_bresp,
  output wire s_axil_bvalid,
  input logic s_axil_bready,
  input logic [15:0] s_axil_araddr,
  input logic s_axil_arvalid,
  output wire s_axil_arready,
  output wire [31:0] s_axil_rdata,
  output wire [1:0] s_axil_rresp,
  output wire s_axil_rvalid,
  input logic s_axil_rready,
  output wire npu_busy,irq,
  input logic host_mode,
  input logic [31:0] h_awaddr,h_wdata,h_araddr,
  input logic [7:0] h_awlen,h_arlen,
  input logic h_awvalid,h_wvalid,h_wlast,h_bready,h_arvalid,h_rready,
  input logic [3:0] h_wstrb,
  output wire h_awready,h_wready,h_bvalid,h_arready,h_rvalid,h_rlast,
  output wire [1:0] h_bresp,h_rresp,
  output wire [31:0] h_rdata,
  output logic [63:0] npu_read_bytes,npu_write_bytes,npu_read_bursts
);
  wire n_arvalid,n_arready,n_rvalid,n_rready,n_rlast;
  wire n_awvalid,n_awready,n_wvalid,n_wready,n_wlast,n_bvalid,n_bready;
  wire [31:0] n_araddr,n_rdata,n_awaddr,n_wdata;
  wire [7:0] n_arlen,n_awlen;
  wire [2:0] n_arsize,n_awsize,n_arprot,n_awprot;
  wire [1:0] n_arburst,n_awburst,n_rresp,n_bresp,n_arlock,n_awlock;
  wire [3:0] n_arcache,n_awcache,n_wstrb;
  wire ram_arready,ram_rvalid,ram_rlast,ram_awready,ram_wready,ram_bvalid;
  wire [31:0] ram_rdata;
  wire [1:0] ram_rresp,ram_bresp;

  npu_axil_top #(.SIZE(SIZE),.PS_FRAME_COUNT(16),.ENABLE_PER_CHANNEL(ENABLE_PER_CHANNEL),
    .ENABLE_IS_MODE(ENABLE_IS_MODE),.WEIGHT_WIDTH(WEIGHT_WIDTH),.ENABLE_CLOCK_GATING(1),
    .ENABLE_VECTOR_ENGINE(ENABLE_VECTOR_ENGINE),.VECTOR_PE_COUNT(VECTOR_PE_COUNT)) dut (
    .clk,.rst_n,.s_axil_awaddr,.s_axil_awprot(3'd0),.s_axil_awvalid,.s_axil_awready,
    .s_axil_wdata,.s_axil_wstrb,.s_axil_wvalid,.s_axil_wready,
    .s_axil_bresp,.s_axil_bvalid,.s_axil_bready,
    .s_axil_araddr,.s_axil_arprot(3'd0),.s_axil_arvalid,.s_axil_arready,
    .s_axil_rdata,.s_axil_rresp,.s_axil_rvalid,.s_axil_rready,
    .m_axi_arvalid(n_arvalid),.m_axi_arready(n_arready),.m_axi_araddr(n_araddr),
    .m_axi_arcache(n_arcache),.m_axi_arprot(n_arprot),.m_axi_arlock(n_arlock),
    .m_axi_arburst(n_arburst),.m_axi_arlen(n_arlen),.m_axi_arsize(n_arsize),
    .m_axi_rvalid(n_rvalid),.m_axi_rready(n_rready),.m_axi_rdata(n_rdata),
    .m_axi_rresp(n_rresp),.m_axi_rlast(n_rlast),
    .m_axi_awvalid(n_awvalid),.m_axi_awready(n_awready),.m_axi_awaddr(n_awaddr),
    .m_axi_awcache(n_awcache),.m_axi_awprot(n_awprot),.m_axi_awlock(n_awlock),
    .m_axi_awburst(n_awburst),.m_axi_awlen(n_awlen),.m_axi_awsize(n_awsize),
    .m_axi_wvalid(n_wvalid),.m_axi_wready(n_wready),.m_axi_wdata(n_wdata),
    .m_axi_wstrb(n_wstrb),.m_axi_wlast(n_wlast),
    .m_axi_bvalid(n_bvalid),.m_axi_bready(n_bready),.m_axi_bresp(n_bresp),.irq,.npu_busy
  );
  soc_axi_ram #(.DP(RAM_WORDS),.DW(32),.AW(32),.READ_OUTSTANDING(4),.WRITE_OUTSTANDING(4)) ram (
    .clk,.rst_n,.mem_reload_req(1'b0),
    .s_axi_awvalid(host_mode?h_awvalid:n_awvalid),.s_axi_awready(ram_awready),
    .s_axi_awaddr(host_mode?h_awaddr:n_awaddr),.s_axi_awcache(host_mode?4'd0:n_awcache),
    .s_axi_awprot(host_mode?3'd0:n_awprot),.s_axi_awlock(host_mode?2'd0:n_awlock),
    .s_axi_awburst(host_mode?2'd1:n_awburst),.s_axi_awlen(host_mode?h_awlen:n_awlen),
    .s_axi_awsize(host_mode?3'd2:n_awsize),
    .s_axi_wvalid(host_mode?h_wvalid:n_wvalid),.s_axi_wready(ram_wready),
    .s_axi_wdata(host_mode?h_wdata:n_wdata),.s_axi_wstrb(host_mode?h_wstrb:n_wstrb),
    .s_axi_wlast(host_mode?h_wlast:n_wlast),
    .s_axi_bvalid(ram_bvalid),.s_axi_bready(host_mode?h_bready:n_bready),.s_axi_bresp(ram_bresp),
    .s_axi_arvalid(host_mode?h_arvalid:n_arvalid),.s_axi_arready(ram_arready),
    .s_axi_araddr(host_mode?h_araddr:n_araddr),.s_axi_arcache(host_mode?4'd0:n_arcache),
    .s_axi_arprot(host_mode?3'd0:n_arprot),.s_axi_arlock(host_mode?2'd0:n_arlock),
    .s_axi_arburst(host_mode?2'd1:n_arburst),.s_axi_arlen(host_mode?h_arlen:n_arlen),
    .s_axi_arsize(host_mode?3'd2:n_arsize),
    .s_axi_rvalid(ram_rvalid),.s_axi_rready(host_mode?h_rready:n_rready),
    .s_axi_rdata(ram_rdata),.s_axi_rresp(ram_rresp),.s_axi_rlast(ram_rlast)
  );
  assign n_arready=!host_mode && ram_arready;
  assign n_rvalid=!host_mode && ram_rvalid;
  assign n_rdata=ram_rdata; assign n_rresp=ram_rresp; assign n_rlast=ram_rlast;
  assign n_awready=!host_mode && ram_awready;
  assign n_wready=!host_mode && ram_wready;
  assign n_bvalid=!host_mode && ram_bvalid; assign n_bresp=ram_bresp;
  assign h_arready=host_mode && ram_arready;
  assign h_rvalid=host_mode && ram_rvalid;
  assign h_rdata=ram_rdata; assign h_rresp=ram_rresp; assign h_rlast=ram_rlast;
  assign h_awready=host_mode && ram_awready;
  assign h_wready=host_mode && ram_wready;
  assign h_bvalid=host_mode && ram_bvalid; assign h_bresp=ram_bresp;
  always_ff @(posedge clk) begin
    if (!rst_n) begin npu_read_bytes<=0;npu_write_bytes<=0;npu_read_bursts<=0; end
    else begin
      if (ENABLE_PER_CHANNEL == 0)
        assert (!(n_arvalid || n_awvalid || n_wvalid))
          else $fatal(1,"disabled Conv attempted an external memory transaction");
      if(n_arvalid && n_arready) begin
        npu_read_bytes<=npu_read_bytes+((64'(n_arlen)+1)<<n_arsize);
        npu_read_bursts<=npu_read_bursts+1;
        assert (32'(n_araddr[11:0])+((32'(n_arlen)+1)<<n_arsize)<=4096)
          else $fatal(1,"NPU read burst crossed 4KiB");
      end
      if(n_wvalid && n_wready) npu_write_bytes<=npu_write_bytes+64'($countones(n_wstrb));
      if(host_mode) assert(!npu_busy) else $fatal(1,"host took memory during NPU task");
    end
  end
endmodule
