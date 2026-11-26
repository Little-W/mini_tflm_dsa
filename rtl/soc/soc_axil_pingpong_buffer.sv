// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 分别缓存 AXI-Lite 五个通道的数据与握手状态，支持读写背压。
module soc_axil_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk /* 模块工作时钟。 */,
    input  wire                         rst_n /* 低电平有效复位。 */,

    input  wire [ADDR_WIDTH-1:0]        s_axil_awaddr /* AXI-Lite 从接口的写地址。 */,
    input  wire [2:0]                   s_axil_awprot /* AXI-Lite 从接口的写访问保护属性。 */,
    input  wire                         s_axil_awvalid /* AXI-Lite 从接口的写地址有效。 */,
    output wire                         s_axil_awready /* AXI-Lite 从接口的可接收写地址。 */,
    input  wire [DATA_WIDTH-1:0]        s_axil_wdata /* AXI-Lite 从接口的写入数据。 */,
    input  wire [DATA_WIDTH/8-1:0]      s_axil_wstrb /* AXI-Lite 从接口的写入字节使能。 */,
    input  wire                         s_axil_wvalid /* AXI-Lite 从接口的写数据有效。 */,
    output wire                         s_axil_wready /* AXI-Lite 从接口的可接收写数据。 */,
    output wire [1:0]                   s_axil_bresp /* AXI-Lite 从接口的写响应状态。 */,
    output wire                         s_axil_bvalid /* AXI-Lite 从接口的写响应有效。 */,
    input  wire                         s_axil_bready /* AXI-Lite 从接口的可接收写响应。 */,
    input  wire [ADDR_WIDTH-1:0]        s_axil_araddr /* AXI-Lite 从接口的读地址。 */,
    input  wire [2:0]                   s_axil_arprot /* AXI-Lite 从接口的读访问保护属性。 */,
    input  wire                         s_axil_arvalid /* AXI-Lite 从接口的读地址有效。 */,
    output wire                         s_axil_arready /* AXI-Lite 从接口的可接收读地址。 */,
    output wire [DATA_WIDTH-1:0]        s_axil_rdata /* AXI-Lite 从接口的读取数据。 */,
    output wire [1:0]                   s_axil_rresp /* AXI-Lite 从接口的读响应状态。 */,
    output wire                         s_axil_rvalid /* AXI-Lite 从接口的读响应有效。 */,
    input  wire                         s_axil_rready /* AXI-Lite 从接口的可接收读响应。 */,

    output wire [ADDR_WIDTH-1:0]        m_axil_awaddr /* AXI-Lite 主接口的写地址。 */,
    output wire [2:0]                   m_axil_awprot /* AXI-Lite 主接口的写访问保护属性。 */,
    output wire                         m_axil_awvalid /* AXI-Lite 主接口的写地址有效。 */,
    input  wire                         m_axil_awready /* AXI-Lite 主接口的可接收写地址。 */,
    output wire [DATA_WIDTH-1:0]        m_axil_wdata /* AXI-Lite 主接口的写入数据。 */,
    output wire [DATA_WIDTH/8-1:0]      m_axil_wstrb /* AXI-Lite 主接口的写入字节使能。 */,
    output wire                         m_axil_wvalid /* AXI-Lite 主接口的写数据有效。 */,
    input  wire                         m_axil_wready /* AXI-Lite 主接口的可接收写数据。 */,
    input  wire [1:0]                   m_axil_bresp /* AXI-Lite 主接口的写响应状态。 */,
    input  wire                         m_axil_bvalid /* AXI-Lite 主接口的写响应有效。 */,
    output wire                         m_axil_bready /* AXI-Lite 主接口的可接收写响应。 */,
    output wire [ADDR_WIDTH-1:0]        m_axil_araddr /* AXI-Lite 主接口的读地址。 */,
    output wire [2:0]                   m_axil_arprot /* AXI-Lite 主接口的读访问保护属性。 */,
    output wire                         m_axil_arvalid /* AXI-Lite 主接口的读地址有效。 */,
    input  wire                         m_axil_arready /* AXI-Lite 主接口的可接收读地址。 */,
    input  wire [DATA_WIDTH-1:0]        m_axil_rdata /* AXI-Lite 主接口的读取数据。 */,
    input  wire [1:0]                   m_axil_rresp /* AXI-Lite 主接口的读响应状态。 */,
    input  wire                         m_axil_rvalid /* AXI-Lite 主接口的读响应有效。 */,
    output wire                         m_axil_rready /* AXI-Lite 主接口的可接收读响应。 */
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
