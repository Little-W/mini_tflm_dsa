// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axi_pingpong_buffer #(
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
    input  wire                         s_axi_awvalid,
    output wire                         s_axi_awready,
    input  wire [ADDR_WIDTH-1:0]        s_axi_awaddr,
    input  wire [3:0]                   s_axi_awcache,
    input  wire [2:0]                   s_axi_awprot,
    input  wire [1:0]                   s_axi_awlock,
    input  wire [1:0]                   s_axi_awburst,
    input  wire [7:0]                   s_axi_awlen,
    input  wire [2:0]                   s_axi_awsize,
    input  wire                         s_axi_wvalid,
    output wire                         s_axi_wready,
    input  wire [DATA_WIDTH-1:0]        s_axi_wdata,
    input  wire [DATA_WIDTH/8-1:0]      s_axi_wstrb,
    input  wire                         s_axi_wlast,
    output wire                         s_axi_bvalid,
    input  wire                         s_axi_bready,
    output wire [1:0]                   s_axi_bresp,

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
    input  wire                         m_axi_rlast,
    output wire                         m_axi_awvalid,
    input  wire                         m_axi_awready,
    output wire [ADDR_WIDTH-1:0]        m_axi_awaddr,
    output wire [3:0]                   m_axi_awcache,
    output wire [2:0]                   m_axi_awprot,
    output wire [1:0]                   m_axi_awlock,
    output wire [1:0]                   m_axi_awburst,
    output wire [7:0]                   m_axi_awlen,
    output wire [2:0]                   m_axi_awsize,
    output wire                         m_axi_wvalid,
    input  wire                         m_axi_wready,
    output wire [DATA_WIDTH-1:0]        m_axi_wdata,
    output wire [DATA_WIDTH/8-1:0]      m_axi_wstrb,
    output wire                         m_axi_wlast,
    input  wire                         m_axi_bvalid,
    output wire                         m_axi_bready,
    input  wire [1:0]                   m_axi_bresp
);

    localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;
    localparam int unsigned AR_WIDTH = ADDR_WIDTH + 4 + 3 + 2 + 2 + 8 + 3;
    localparam int unsigned AW_WIDTH = AR_WIDTH;
    localparam int unsigned W_WIDTH  = DATA_WIDTH + STRB_WIDTH + 1;
    localparam int unsigned R_WIDTH  = DATA_WIDTH + 2 + 1;
    localparam int unsigned B_WIDTH  = 2;

    wire [AR_WIDTH-1:0] s_ar_payload;
    wire [AR_WIDTH-1:0] m_ar_payload;
    wire [AW_WIDTH-1:0] s_aw_payload;
    wire [AW_WIDTH-1:0] m_aw_payload;
    wire [W_WIDTH-1:0]  s_w_payload;
    wire [W_WIDTH-1:0]  m_w_payload;
    wire [R_WIDTH-1:0]  s_r_payload;
    wire [R_WIDTH-1:0]  m_r_payload;
    wire [B_WIDTH-1:0]  s_b_payload;
    wire [B_WIDTH-1:0]  m_b_payload;

    assign s_ar_payload = {s_axi_araddr, s_axi_arcache, s_axi_arprot,
                           s_axi_arlock, s_axi_arburst, s_axi_arlen,
                           s_axi_arsize};
    assign {m_axi_araddr, m_axi_arcache, m_axi_arprot, m_axi_arlock,
            m_axi_arburst, m_axi_arlen, m_axi_arsize} = m_ar_payload;

    assign s_aw_payload = {s_axi_awaddr, s_axi_awcache, s_axi_awprot,
                           s_axi_awlock, s_axi_awburst, s_axi_awlen,
                           s_axi_awsize};
    assign {m_axi_awaddr, m_axi_awcache, m_axi_awprot, m_axi_awlock,
            m_axi_awburst, m_axi_awlen, m_axi_awsize} = m_aw_payload;

    assign s_w_payload = {s_axi_wdata, s_axi_wstrb, s_axi_wlast};
    assign {m_axi_wdata, m_axi_wstrb, m_axi_wlast} = m_w_payload;

    assign s_r_payload = {m_axi_rdata, m_axi_rresp, m_axi_rlast};
    assign {s_axi_rdata, s_axi_rresp, s_axi_rlast} = m_r_payload;

    assign s_b_payload = m_axi_bresp;
    assign s_axi_bresp = m_b_payload;

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

    soc_axi_pingpong_chan #(.WIDTH(AW_WIDTH)) u_aw_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axi_awvalid),
        .s_ready(s_axi_awready),
        .s_data(s_aw_payload),
        .m_valid(m_axi_awvalid),
        .m_ready(m_axi_awready),
        .m_data(m_aw_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(W_WIDTH)) u_w_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axi_wvalid),
        .s_ready(s_axi_wready),
        .s_data(s_w_payload),
        .m_valid(m_axi_wvalid),
        .m_ready(m_axi_wready),
        .m_data(m_w_payload)
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

    soc_axi_pingpong_chan #(.WIDTH(B_WIDTH)) u_b_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(m_axi_bvalid),
        .s_ready(m_axi_bready),
        .s_data(s_b_payload),
        .m_valid(s_axi_bvalid),
        .m_ready(s_axi_bready),
        .m_data(m_b_payload)
    );

endmodule

`default_nettype wire
