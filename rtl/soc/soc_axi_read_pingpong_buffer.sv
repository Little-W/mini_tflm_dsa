// SPDX-License-Identifier: Apache-2.0
`default_nettype none
// 缓存 AXI 读地址与读响应，保持背压期间的地址、数据和突发结束标志。
module soc_axi_read_pingpong_buffer #(
    parameter int unsigned ADDR_WIDTH = 32,
    parameter int unsigned DATA_WIDTH = 32
) (
    input  wire                         clk /* 模块工作时钟。 */,
    input  wire                         rst_n /* 低电平有效复位。 */,

    input  wire                         s_axi_arvalid /* AXI 从接口的读地址有效。 */,
    output wire                         s_axi_arready /* AXI 从接口的可接收读地址。 */,
    input  wire [ADDR_WIDTH-1:0]        s_axi_araddr /* AXI 从接口的读地址。 */,
    input  wire [3:0]                   s_axi_arcache /* AXI 从接口的读事务缓存属性。 */,
    input  wire [2:0]                   s_axi_arprot /* AXI 从接口的读访问保护属性。 */,
    input  wire [1:0]                   s_axi_arlock /* AXI 从接口的读事务锁定属性。 */,
    input  wire [1:0]                   s_axi_arburst /* AXI 从接口的读突发地址模式。 */,
    input  wire [7:0]                   s_axi_arlen /* AXI 从接口的读突发拍数减一。 */,
    input  wire [2:0]                   s_axi_arsize /* AXI 从接口的读取每拍字节数的以二为底对数。 */,
    output wire                         s_axi_rvalid /* AXI 从接口的读响应有效。 */,
    input  wire                         s_axi_rready /* AXI 从接口的可接收读响应。 */,
    output wire [DATA_WIDTH-1:0]        s_axi_rdata /* AXI 从接口的读取数据。 */,
    output wire [1:0]                   s_axi_rresp /* AXI 从接口的读响应状态。 */,
    output wire                         s_axi_rlast /* AXI 从接口的读突发的最后一拍。 */,

    output wire                         m_axi_arvalid /* AXI 主接口的读地址有效。 */,
    input  wire                         m_axi_arready /* AXI 主接口的可接收读地址。 */,
    output wire [ADDR_WIDTH-1:0]        m_axi_araddr /* AXI 主接口的读地址。 */,
    output wire [3:0]                   m_axi_arcache /* AXI 主接口的读事务缓存属性。 */,
    output wire [2:0]                   m_axi_arprot /* AXI 主接口的读访问保护属性。 */,
    output wire [1:0]                   m_axi_arlock /* AXI 主接口的读事务锁定属性。 */,
    output wire [1:0]                   m_axi_arburst /* AXI 主接口的读突发地址模式。 */,
    output wire [7:0]                   m_axi_arlen /* AXI 主接口的读突发拍数减一。 */,
    output wire [2:0]                   m_axi_arsize /* AXI 主接口的读取每拍字节数的以二为底对数。 */,
    input  wire                         m_axi_rvalid /* AXI 主接口的读响应有效。 */,
    output wire                         m_axi_rready /* AXI 主接口的可接收读响应。 */,
    input  wire [DATA_WIDTH-1:0]        m_axi_rdata /* AXI 主接口的读取数据。 */,
    input  wire [1:0]                   m_axi_rresp /* AXI 主接口的读响应状态。 */,
    input  wire                         m_axi_rlast /* AXI 主接口的读突发的最后一拍。 */
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
