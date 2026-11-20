module read_ready_top #(
    parameter int REG_WIDTH=32, BUS_WIDTH=64, READ_OUTSTANDING=4
) (
    input logic clk, rst_n, cfg_fire, conv_enable, dma_range_enable,
    input logic [31:0] conv_range_base[4],
    input logic [32:0] conv_range_end[4],
    input logic linear_arvalid, linear_rready,
    input logic [REG_WIDTH-1:0] linear_araddr,
    input logic [7:0] linear_arlen,
    input logic [2:0] linear_arsize,
    input logic [1:0] linear_arburst,
    output logic linear_arready, linear_rvalid, linear_rlast,
    output logic [BUS_WIDTH-1:0] linear_rdata,
    output logic [1:0] linear_rresp,
    input logic fe_arvalid, fe_rready,
    input logic [REG_WIDTH-1:0] fe_araddr,
    input logic [7:0] fe_arlen,
    input logic [2:0] fe_arsize,
    input logic [1:0] fe_arburst,
    output logic fe_arready, fe_rvalid, fe_rlast,
    output logic [BUS_WIDTH-1:0] fe_rdata,
    output logic [1:0] fe_rresp,
    output logic m_axi_arvalid, m_axi_rready,
    output logic [REG_WIDTH-1:0] m_axi_araddr,
    output logic [7:0] m_axi_arlen,
    output logic [2:0] m_axi_arsize,
    output logic [1:0] m_axi_arburst,
    input logic m_axi_arready, m_axi_rvalid, m_axi_rlast,
    input logic [BUS_WIDTH-1:0] m_axi_rdata,
    input logic [1:0] m_axi_rresp,
    output logic guard_idle, mux_idle, read_error, mode_conv
);
    localparam bit CONV_SUPPORTED=1'b1;
    logic guard_arvalid, guard_arready, guard_rvalid, guard_rready, guard_rlast;
    logic [REG_WIDTH-1:0] guard_araddr;
    logic [BUS_WIDTH-1:0] guard_rdata;
    logic [7:0] guard_arlen;
    logic [2:0] guard_arsize;
    logic [1:0] guard_arburst, guard_rresp;
@@MODE@@
@@INSTANCES@@
    assign read_error=m_axi_rvalid && m_axi_rready && m_axi_rresp[1];
    assign mode_conv=job_conv;
endmodule
