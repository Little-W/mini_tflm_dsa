// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axi_write_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk,
    input  wire                         rst_n,

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
    localparam int unsigned AW_WIDTH = ADDR_WIDTH + 4 + 3 + 2 + 2 + 8 + 3;
    localparam int unsigned W_WIDTH  = DATA_WIDTH + STRB_WIDTH + 1;
    localparam int unsigned B_WIDTH  = 2;

    wire [AW_WIDTH-1:0] s_aw_payload;
    wire [AW_WIDTH-1:0] m_aw_payload;
    wire [W_WIDTH-1:0]  s_w_payload;
    wire [W_WIDTH-1:0]  m_w_payload;
    wire [B_WIDTH-1:0]  s_b_payload;
    wire [B_WIDTH-1:0]  m_b_payload;

    assign s_aw_payload = {s_axi_awaddr, s_axi_awcache, s_axi_awprot,
                           s_axi_awlock, s_axi_awburst, s_axi_awlen,
                           s_axi_awsize};
    assign {m_axi_awaddr, m_axi_awcache, m_axi_awprot, m_axi_awlock,
            m_axi_awburst, m_axi_awlen, m_axi_awsize} = m_aw_payload;

    assign s_w_payload = {s_axi_wdata, s_axi_wstrb, s_axi_wlast};
    assign {m_axi_wdata, m_axi_wstrb, m_axi_wlast} = m_w_payload;

    assign s_b_payload = m_axi_bresp;
    assign s_axi_bresp = m_b_payload;

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
