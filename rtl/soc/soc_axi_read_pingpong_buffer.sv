// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axi_read_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         s_axi_arvalid,
    output wire                         s_axi_arready,
    input  wire [ADDR_WIDTH-1:0]        s_axi_araddr,
    input  wire [3:0]                   s_axi_arcache,
    input  wire [2:0]                   s_axi_arprot,
    input  wire [1:0]                   s_axi_arlock,
    input  wire [1:0]                   s_axi_arburst,
    input  wire [7:0]                   s_axi_arlen,
    input  wire [2:0]                   s_axi_arsize,
    output wire                         s_axi_rvalid,
    input  wire                         s_axi_rready,
    output wire [DATA_WIDTH-1:0]        s_axi_rdata,
    output wire [1:0]                   s_axi_rresp,
    output wire                         s_axi_rlast,

    output wire                         m_axi_arvalid,
    input  wire                         m_axi_arready,
    output wire [ADDR_WIDTH-1:0]        m_axi_araddr,
    output wire [3:0]                   m_axi_arcache,
    output wire [2:0]                   m_axi_arprot,
    output wire [1:0]                   m_axi_arlock,
    output wire [1:0]                   m_axi_arburst,
    output wire [7:0]                   m_axi_arlen,
    output wire [2:0]                   m_axi_arsize,
    input  wire                         m_axi_rvalid,
    output wire                         m_axi_rready,
    input  wire [DATA_WIDTH-1:0]        m_axi_rdata,
    input  wire [1:0]                   m_axi_rresp,
    input  wire                         m_axi_rlast
);

    localparam int unsigned AR_WIDTH = ADDR_WIDTH + 4 + 3 + 2 + 2 + 8 + 3;
    localparam int unsigned R_WIDTH  = DATA_WIDTH + 2 + 1;

    wire [AR_WIDTH-1:0] s_ar_payload;
    wire [AR_WIDTH-1:0] m_ar_payload;
    wire [R_WIDTH-1:0]  s_r_payload;
    wire [R_WIDTH-1:0]  m_r_payload;

    assign s_ar_payload = {s_axi_araddr, s_axi_arcache, s_axi_arprot,
                           s_axi_arlock, s_axi_arburst, s_axi_arlen,
                           s_axi_arsize};
    assign {m_axi_araddr, m_axi_arcache, m_axi_arprot, m_axi_arlock,
            m_axi_arburst, m_axi_arlen, m_axi_arsize} = m_ar_payload;

    assign s_r_payload = {m_axi_rdata, m_axi_rresp, m_axi_rlast};
    assign {s_axi_rdata, s_axi_rresp, s_axi_rlast} = m_r_payload;

    soc_axi_pingpong_chan #(.WIDTH(AR_WIDTH)) u_ar_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axi_arvalid),
        .s_ready(s_axi_arready),
        .s_data(s_ar_payload),
        .m_valid(m_axi_arvalid),
        .m_ready(m_axi_arready),
        .m_data(m_ar_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(R_WIDTH)) u_r_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(m_axi_rvalid),
        .s_ready(m_axi_rready),
        .s_data(s_r_payload),
        .m_valid(s_axi_rvalid),
        .m_ready(s_axi_rready),
        .m_data(m_r_payload)
    );

endmodule

`default_nettype wire
