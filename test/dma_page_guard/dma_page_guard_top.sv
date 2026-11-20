// SPDX-License-Identifier: Apache-2.0
module dma_page_guard_top (
    input logic clk, rst_n,
    input logic s_arvalid, output logic s_arready,
    input logic [31:0] s_araddr, input logic [7:0] s_arlen,
    output logic s_rvalid, input logic s_rready,
    output logic [31:0] s_rdata, output logic [1:0] s_rresp, output logic s_rlast,
    output logic m_arvalid, input logic m_arready,
    output logic [31:0] m_araddr, output logic [7:0] m_arlen,
    output logic [2:0] m_arsize, output logic [1:0] m_arburst,
    input logic m_rvalid, output logic m_rready,
    input logic [31:0] m_rdata, input logic [1:0] m_rresp, input logic m_rlast,
    input logic s_awvalid, output logic s_awready,
    input logic [31:0] s_awaddr, input logic [7:0] s_awlen,
    input logic s_wvalid, output logic s_wready,
    input logic [31:0] s_wdata, input logic [3:0] s_wstrb, input logic s_wlast,
    output logic s_bvalid, input logic s_bready, output logic [1:0] s_bresp,
    output logic m_awvalid, input logic m_awready,
    output logic [31:0] m_awaddr, output logic [7:0] m_awlen,
    output logic [2:0] m_awsize, output logic [1:0] m_awburst,
    output logic m_wvalid, input logic m_wready,
    output logic [31:0] m_wdata, output logic [3:0] m_wstrb, output logic m_wlast,
    input logic m_bvalid, output logic m_bready, input logic [1:0] m_bresp,
    output logic read_idle, write_idle
);
    wire [31:0] cfg_base[4];
    wire [32:0] cfg_end[4];
    assign cfg_base = '{default:'0};
    assign cfg_end = '{default:'0};
    conv_axi_read_guard #(.SPLIT_GEMM_4K(1'b1),.READ_OUTSTANDING(4)) u_read (
        .clk,.rst_n,.enable(1'b0),.cfg_valid(1'b0),.cfg_base,.cfg_end,
        .s_arvalid,.s_arready,.s_araddr,.s_arlen,.s_arsize(3'd2),.s_arburst(2'b01),
        .s_rvalid,.s_rready,.s_rdata,.s_rresp,.s_rlast,
        .m_arvalid,.m_arready,.m_araddr,.m_arlen,.m_arsize,.m_arburst,
        .m_rvalid,.m_rready,.m_rdata,.m_rresp,.m_rlast,.idle(read_idle)
    );
    axi_write_page_guard u_write (
        .clk,.rst_n,.s_awvalid,.s_awready,.s_awaddr,.s_awlen,
        .s_awsize(3'd2),.s_awburst(2'b01),.s_wvalid,.s_wready,.s_wdata,.s_wstrb,.s_wlast,
        .s_bvalid,.s_bready,.s_bresp,.m_awvalid,.m_awready,.m_awaddr,.m_awlen,.m_awsize,.m_awburst,
        .m_wvalid,.m_wready,.m_wdata,.m_wstrb,.m_wlast,.m_bvalid,.m_bready,.m_bresp,.idle(write_idle)
    );
endmodule
