// SPDX-License-Identifier: Apache-2.0
`default_nettype none

module soc_axil_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire [ADDR_WIDTH-1:0]        s_axil_awaddr,
    input  wire [2:0]                   s_axil_awprot,
    input  wire                         s_axil_awvalid,
    output wire                         s_axil_awready,
    input  wire [DATA_WIDTH-1:0]        s_axil_wdata,
    input  wire [DATA_WIDTH/8-1:0]      s_axil_wstrb,
    input  wire                         s_axil_wvalid,
    output wire                         s_axil_wready,
    output wire [1:0]                   s_axil_bresp,
    output wire                         s_axil_bvalid,
    input  wire                         s_axil_bready,
    input  wire [ADDR_WIDTH-1:0]        s_axil_araddr,
    input  wire [2:0]                   s_axil_arprot,
    input  wire                         s_axil_arvalid,
    output wire                         s_axil_arready,
    output wire [DATA_WIDTH-1:0]        s_axil_rdata,
    output wire [1:0]                   s_axil_rresp,
    output wire                         s_axil_rvalid,
    input  wire                         s_axil_rready,

    output wire [ADDR_WIDTH-1:0]        m_axil_awaddr,
    output wire [2:0]                   m_axil_awprot,
    output wire                         m_axil_awvalid,
    input  wire                         m_axil_awready,
    output wire [DATA_WIDTH-1:0]        m_axil_wdata,
    output wire [DATA_WIDTH/8-1:0]      m_axil_wstrb,
    output wire                         m_axil_wvalid,
    input  wire                         m_axil_wready,
    input  wire [1:0]                   m_axil_bresp,
    input  wire                         m_axil_bvalid,
    output wire                         m_axil_bready,
    output wire [ADDR_WIDTH-1:0]        m_axil_araddr,
    output wire [2:0]                   m_axil_arprot,
    output wire                         m_axil_arvalid,
    input  wire                         m_axil_arready,
    input  wire [DATA_WIDTH-1:0]        m_axil_rdata,
    input  wire [1:0]                   m_axil_rresp,
    input  wire                         m_axil_rvalid,
    output wire                         m_axil_rready
);

    localparam int unsigned STRB_WIDTH = DATA_WIDTH / 8;
    localparam int unsigned AW_WIDTH = ADDR_WIDTH + 3;
    localparam int unsigned W_WIDTH  = DATA_WIDTH + STRB_WIDTH;
    localparam int unsigned B_WIDTH  = 2;
    localparam int unsigned AR_WIDTH = ADDR_WIDTH + 3;
    localparam int unsigned R_WIDTH  = DATA_WIDTH + 2;

    wire [AW_WIDTH-1:0] s_aw_payload;
    wire [AW_WIDTH-1:0] m_aw_payload;
    wire [W_WIDTH-1:0]  s_w_payload;
    wire [W_WIDTH-1:0]  m_w_payload;
    wire [B_WIDTH-1:0]  s_b_payload;
    wire [B_WIDTH-1:0]  m_b_payload;
    wire [AR_WIDTH-1:0] s_ar_payload;
    wire [AR_WIDTH-1:0] m_ar_payload;
    wire [R_WIDTH-1:0]  s_r_payload;
    wire [R_WIDTH-1:0]  m_r_payload;

    assign s_aw_payload = {s_axil_awaddr, s_axil_awprot};
    assign {m_axil_awaddr, m_axil_awprot} = m_aw_payload;

    assign s_w_payload = {s_axil_wdata, s_axil_wstrb};
    assign {m_axil_wdata, m_axil_wstrb} = m_w_payload;

    assign s_b_payload = m_axil_bresp;
    assign s_axil_bresp = m_b_payload;

    assign s_ar_payload = {s_axil_araddr, s_axil_arprot};
    assign {m_axil_araddr, m_axil_arprot} = m_ar_payload;

    assign s_r_payload = {m_axil_rdata, m_axil_rresp};
    assign {s_axil_rdata, s_axil_rresp} = m_r_payload;

    soc_axi_pingpong_chan #(.WIDTH(AW_WIDTH)) u_aw_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axil_awvalid),
        .s_ready(s_axil_awready),
        .s_data(s_aw_payload),
        .m_valid(m_axil_awvalid),
        .m_ready(m_axil_awready),
        .m_data(m_aw_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(W_WIDTH)) u_w_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axil_wvalid),
        .s_ready(s_axil_wready),
        .s_data(s_w_payload),
        .m_valid(m_axil_wvalid),
        .m_ready(m_axil_wready),
        .m_data(m_w_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(B_WIDTH)) u_b_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(m_axil_bvalid),
        .s_ready(m_axil_bready),
        .s_data(s_b_payload),
        .m_valid(s_axil_bvalid),
        .m_ready(s_axil_bready),
        .m_data(m_b_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(AR_WIDTH)) u_ar_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(s_axil_arvalid),
        .s_ready(s_axil_arready),
        .s_data(s_ar_payload),
        .m_valid(m_axil_arvalid),
        .m_ready(m_axil_arready),
        .m_data(m_ar_payload)
    );

    soc_axi_pingpong_chan #(.WIDTH(R_WIDTH)) u_r_buf (
        .clk(clk),
        .rst_n(rst_n),
        .s_valid(m_axil_rvalid),
        .s_ready(m_axil_rready),
        .s_data(s_r_payload),
        .m_valid(s_axil_rvalid),
        .m_ready(s_axil_rready),
        .m_data(m_r_payload)
    );

endmodule

`default_nettype wire
