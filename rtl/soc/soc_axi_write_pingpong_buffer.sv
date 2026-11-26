// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 缓存 AXI 写地址、写数据与写响应，分别处理各通道握手。
module soc_axi_write_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk /* 模块工作时钟。 */,
    input  wire                         rst_n /* 低电平有效复位。 */,

    input  wire                         s_axi_awvalid /* AXI 从接口的写地址有效。 */,
    output wire                         s_axi_awready /* AXI 从接口的可接收写地址。 */,
    input  wire [ADDR_WIDTH-1:0]        s_axi_awaddr /* AXI 从接口的写地址。 */,
    input  wire [3:0]                   s_axi_awcache /* AXI 从接口的写事务缓存属性。 */,
    input  wire [2:0]                   s_axi_awprot /* AXI 从接口的写访问保护属性。 */,
    input  wire [1:0]                   s_axi_awlock /* AXI 从接口的写事务锁定属性。 */,
    input  wire [1:0]                   s_axi_awburst /* AXI 从接口的写突发地址模式。 */,
    input  wire [7:0]                   s_axi_awlen /* AXI 从接口的写突发拍数减一。 */,
    input  wire [2:0]                   s_axi_awsize /* AXI 从接口的写入每拍字节数的以二为底对数。 */,
    input  wire                         s_axi_wvalid /* AXI 从接口的写数据有效。 */,
    output wire                         s_axi_wready /* AXI 从接口的可接收写数据。 */,
    input  wire [DATA_WIDTH-1:0]        s_axi_wdata /* AXI 从接口的写入数据。 */,
    input  wire [DATA_WIDTH/8-1:0]      s_axi_wstrb /* AXI 从接口的写入字节使能。 */,
    input  wire                         s_axi_wlast /* AXI 从接口的写突发的最后一拍。 */,
    output wire                         s_axi_bvalid /* AXI 从接口的写响应有效。 */,
    input  wire                         s_axi_bready /* AXI 从接口的可接收写响应。 */,
    output wire [1:0]                   s_axi_bresp /* AXI 从接口的写响应状态。 */,

    output wire                         m_axi_awvalid /* AXI 主接口的写地址有效。 */,
    input  wire                         m_axi_awready /* AXI 主接口的可接收写地址。 */,
    output wire [ADDR_WIDTH-1:0]        m_axi_awaddr /* AXI 主接口的写地址。 */,
    output wire [3:0]                   m_axi_awcache /* AXI 主接口的写事务缓存属性。 */,
    output wire [2:0]                   m_axi_awprot /* AXI 主接口的写访问保护属性。 */,
    output wire [1:0]                   m_axi_awlock /* AXI 主接口的写事务锁定属性。 */,
    output wire [1:0]                   m_axi_awburst /* AXI 主接口的写突发地址模式。 */,
    output wire [7:0]                   m_axi_awlen /* AXI 主接口的写突发拍数减一。 */,
    output wire [2:0]                   m_axi_awsize /* AXI 主接口的写入每拍字节数的以二为底对数。 */,
    output wire                         m_axi_wvalid /* AXI 主接口的写数据有效。 */,
    input  wire                         m_axi_wready /* AXI 主接口的可接收写数据。 */,
    output wire [DATA_WIDTH-1:0]        m_axi_wdata /* AXI 主接口的写入数据。 */,
    output wire [DATA_WIDTH/8-1:0]      m_axi_wstrb /* AXI 主接口的写入字节使能。 */,
    output wire                         m_axi_wlast /* AXI 主接口的写突发的最后一拍。 */,
    input  wire                         m_axi_bvalid /* AXI 主接口的写响应有效。 */,
    output wire                         m_axi_bready /* AXI 主接口的可接收写响应。 */,
    input  wire [1:0]                   m_axi_bresp /* AXI 主接口的写响应状态。 */
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
